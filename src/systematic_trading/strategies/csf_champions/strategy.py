"""Lumibot adapter for the CSF Champions strategy.

Startup pipeline (runs once in ``initialize``): generate trade ideas (skipped
when ``trade_ideas_generated`` is True), then build the draft portfolio via the
portfolio-constructor agent. Trade submission is a later step, not yet designed.
"""

from lumibot.strategies import Strategy

from systematic_trading.logging_setup import get_logger
from systematic_trading.strategies.csf_champions.portfolio import Portfolio
from systematic_trading.strategies.csf_champions.workflows.build_portfolio import (
    construct_portfolio,
)
from systematic_trading.strategies.csf_champions.workflows.generate_trade_ideas import (
    generate_trade_ideas,
)

log = get_logger(__name__)


class CsfChampions(Strategy):
    """CSF Champions: agent-scored fundamentals book, long-only sleeve."""

    WARM_UP_TRADING_DAYS = 0

    parameters = {
        # True -> ideas already sit in DynamoDB; skip the (expensive) agent run.
        "trade_ideas_generated": False,
    }

    # This is the first function that runs, it runs once at the beginning of the entire strategy run
    def initialize(self) -> None:
        self.sleeptime = "1D"

        # The draft book is stateful across the whole strategy run: created
        # empty here, seeded and shaped by build_portfolio, read by submission.
        self.portfolio = Portfolio()

        if self.parameters["trade_ideas_generated"]:
            log.info("Trade ideas already generated — pulling from DynamoDB")
        else:
            log.info("Generating trade ideas")
            generate_trade_ideas()

        construct_portfolio(self.portfolio)

        # TODO: submit-trades workflow (not yet designed).

    def on_trading_iteration(self) -> None:
        pass
