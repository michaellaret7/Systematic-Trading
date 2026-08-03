"""Lumibot adapter for the CSF Champions strategy.

Startup pipeline (runs once in ``initialize``, gated by ``build_portfolio``):
generate trade ideas (only when ``generate_ideas`` is True), build the draft
portfolio via the portfolio-constructor agent, then submit the book as
whole-share market buys on Alpaca.

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
)

log = get_logger(__name__)


class CsfChampions(Strategy):
    """CSF Champions: agent-scored fundamentals book, long-only sleeve."""

    WARM_UP_TRADING_DAYS = 0

    parameters = {
        "generate_ideas": False,
        "build_portfolio": True,
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
        """Daily strategy heartbeat."""
        log.info("CSF Champions daily trading iteration")

        # check → review breaches → record only successful agent finishes
        # (no-ops while names are locked in drawdown_reviews)
        # manage_drawdowns(self, self.portfolio)

    def after_market_closes(self) -> None:
        """After market closes: check for new drawdown breaches and review them."""
        # If there are any open orders thaty expired, re enter them to be filled the next trading day
