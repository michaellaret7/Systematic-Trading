"""Lumibot adapter for the CSF Champions strategy.

Startup pipeline (runs once in ``initialize``, gated by ``build_portfolio``):
generate trade ideas (only when ``generate_ideas`` is True), build the draft
portfolio via the portfolio-constructor agent, then submit the book as
whole-share market buys on Alpaca.

Daily risk loop:
- ``before_market_opens`` — drop expired drawdown cooldowns
- ``on_trading_iteration`` — submit any pending risk orders from the prior
  after-close review (sells before buys)
- ``after_market_closes`` — run the drawdown agent and stash actionable orders
  for the next session

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

    def initialize(self) -> None:
        # Run the strategy heartbeat once per trading day.
        self.sleeptime = "2H"

        # The draft book is stateful across the whole strategy run: created
        # empty here, seeded and shaped by build_portfolio, read by submission.
        self.portfolio = Portfolio()

        # The flag is the single switch: only run the startup pipeline
        # (idea generation, construction, submission) when explicitly asked.
        if not self.parameters["build_portfolio"]:
            log.info("build_portfolio is off - skipping startup pipeline")
            return

        if self.parameters["generate_ideas"]:
            log.info("Generating trade ideas")
            generate_trade_ideas()
        else:
            log.info("Using existing trade ideas from DynamoDB")

        construct_portfolio(self.portfolio)

        # Push the finalized draft book to the broker as whole-share market buys.
        enter_positions(self, self.portfolio)

    def before_market_opens(self) -> None:
        """Drop agent-reviewed drawdowns whose two-week cooldown has expired."""
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
        """Intraday heartbeat: apply any pending risk orders, nothing else."""
        log.info("CSF Champions trading iteration")

    def after_market_closes(self) -> None:
        """After close: review new drawdown breaches; stash orders for next open."""
        log.info("After market closes: running drawdown risk review")

        orders = manage_drawdowns(self, self.portfolio)

        if orders:
            log.info(
                "After market closes: %d actionable drawdown order(s) queued for next session: %s",
                len(orders),
                ", ".join(f"{decision.ticker}:{decision.action}" for _breach, decision in orders),
            )
        else:
            log.info("After market closes: no actionable drawdown orders")
