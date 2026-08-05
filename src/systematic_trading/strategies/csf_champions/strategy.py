"""Lumibot adapter for the CSF Champions strategy.

Startup pipeline (runs once in ``initialize``, gated by ``build_portfolio``):
generate trade ideas (only when ``generate_ideas`` is True), build the draft
portfolio via the portfolio-constructor agent, then submit the book as
whole-share market buys on Alpaca.

Daily risk loop:
- ``before_market_opens`` — drop expired drawdown cooldowns
- ``after_market_closes`` — run the drawdown agent, size, and stash sells/buys
- ``flush_pending_drawdown_orders`` (10:00 weekday cron) — submit pending
  market orders (sells before buys); the book drains itself as it goes

Broker state (positions, fills, cash) is read from Alpaca. DynamoDB is used
only for the trade-ideas queue.
"""

from lumibot.strategies import Strategy

from systematic_trading.logging_setup import get_logger
from systematic_trading.strategies.csf_champions.portfolio import Portfolio
from systematic_trading.strategies.csf_champions.workflows.build_portfolio import (
    construct_portfolio,
)
from systematic_trading.strategies.csf_champions.workflows.enter_positions import (
    enter_positions,
)
from systematic_trading.strategies.csf_champions.workflows.generate_trade_ideas import (
    generate_trade_ideas,
)
from systematic_trading.strategies.csf_champions.workflows.rsk_mgmt import (
    SizedOrder,
    clear_expired_drawdown_reviews,
    manage_drawdowns,
    submit_drawdown_orders,
)

log = get_logger(__name__)


class CsfChampions(Strategy):
    """CSF Champions: agent-scored fundamentals book, long-only sleeve."""

    WARM_UP_TRADING_DAYS = 0

    parameters = {
        "generate_ideas": False,
        "build_portfolio": False,
    }

    #     ================================
    # --> Startup
    #     ================================

    def initialize(self) -> None:
        """One-time setup: cadence, portfolio, pending book, cron, optional build."""

        # Heartbeat while the market is open (risk submits use the 10:00 cron).
        self.sleeptime = "2H"

        # Draft book for the optional startup construction pipeline.
        self.portfolio = Portfolio()

        # Overnight risk order stash for the 10:00 flush.
        self.pending_sells: list[SizedOrder] = []
        self.pending_buys: list[SizedOrder] = []

        # 10:00 Mon–Fri: pass the method reference — do not call it here.
        # Lumibot builds the trigger with `timezone=self.pytz`, which is the
        # data source's tz (America/New_York by default), so this is 10:00 ET
        # regardless of the droplet clock. It also skips registration entirely
        # when backtesting — `on_trading_iteration` covers that case.
        self.register_cron_callback("0 10 * * 1-5", self.flush_pending_drawdown_orders)

        # Optional one-shot build: ideas → construct → enter. Off by default.
        if not self.parameters["build_portfolio"]:
            log.info("build_portfolio is off - skipping startup pipeline")
            return

        if self.parameters["generate_ideas"]:
            log.info("Generating trade ideas")
            generate_trade_ideas()
        else:
            log.info("Using existing trade ideas from DynamoDB")

        construct_portfolio(self.portfolio)

        # Whole-share market buys for the finalized draft book.
        enter_positions(self, self.portfolio)

    #     ================================
    # --> Market lifecycle
    #     ================================

    def before_market_opens(self) -> None:
        """Drop drawdown cooldowns that have aged past the review window."""

        evicted = clear_expired_drawdown_reviews(self, self.portfolio)

        if evicted:
            log.info(
                "Before market opens: evicted %d expired drawdown review(s): %s",
                len(evicted),
                ", ".join(sorted(evicted)),
            )
        else:
            log.info("Before market opens: no expired drawdown reviews to evict")

    def on_trading_iteration(self) -> None:
        """Intraday heartbeat. In backtest it also stands in for the 10:00 cron.

        Lumibot skips cron registration when backtesting, so the flush would
        never fire there and the risk loop would be unreachable from a
        backtest. Live, submission stays on the cron alone.
        """

        log.info("CSF Champions trading iteration")

        if self.is_backtesting and (self.pending_sells or self.pending_buys):
            self.flush_pending_drawdown_orders()

    def after_market_closes(self) -> None:
        """Run drawdown review; append any new sized sells/buys into the pending book."""

        log.info("After market closes: running drawdown risk review")

        # Empty = nothing new to queue (no breaches, holds only, or zero-sized).
        # Existing pending rows (e.g. unflushed after a closed 10:00) stay put.
        sells, buys = manage_drawdowns(self, self.portfolio)

        self.pending_sells += sells
        self.pending_buys += buys

        log.info(
            "After market closes: appended %d sell(s), %d buy(s) (book now %d sell(s), %d buy(s)) for 10:00",
            len(sells),
            len(buys),
            len(self.pending_sells),
            len(self.pending_buys),
        )

    #     ================================
    # --> Cron jobs
    #     ================================

    def flush_pending_drawdown_orders(self) -> None:
        """Cron (10:00 weekdays): submit stashed risk orders.

        The book drains itself as each row is attempted, so there is nothing to
        clear here — whatever survives was never sent and is retried next flush.
        """

        if not self.pending_sells and not self.pending_buys:
            log.info("10:00 flush: no pending drawdown orders")
            return

        # False when market is closed — leave the stash for a later day.
        if submit_drawdown_orders(self, self.portfolio, self.pending_sells, self.pending_buys):
            log.info("10:00 flush: pending drawdown book flushed")
        else:
            log.info("10:00 flush: market closed — pending drawdown orders kept")
