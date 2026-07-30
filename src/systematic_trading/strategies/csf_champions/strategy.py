"""Lumibot adapter for the CSF Champions strategy.

Startup pipeline (runs once in ``initialize``, gated by ``build_portfolio``):
generate trade ideas (only when ``generate_ideas`` is True), build the draft
portfolio via the portfolio-constructor agent, then submit the book as
whole-share market buys.

Each fully-filled broker order closes its trade-ledger row and marks its source
idea filled.
"""

from lumibot.entities import Order, Position
from lumibot.strategies import Strategy

from systematic_trading.data.repository import complete_order, update_idea_status
from systematic_trading.logging_setup import get_logger
from systematic_trading.strategies.csf_champions.portfolio import Portfolio
from systematic_trading.strategies.csf_champions.workflows.build_portfolio import (
    construct_portfolio,
)
from systematic_trading.strategies.csf_champions.workflows.enter_positions import (
    STRATEGY,
    enter_positions,
)
from systematic_trading.strategies.csf_champions.workflows.generate_trade_ideas import (
    generate_trade_ideas,
)

log = get_logger(__name__)


"""
Threading queues (queue.Queue) are for passing tasks between threads in one process; if you want true parallelism across cores (relevant for CPU-bound strategy backtests),
the same put/get pattern exists via multiprocessing.Queue for inter-process producer-consumer setups.
"""

class CsfChampions(Strategy):
    """CSF Champions: agent-scored fundamentals book, long-only sleeve."""

    WARM_UP_TRADING_DAYS = 0

    parameters = {
        "generate_ideas": False,
        "build_portfolio": True,
    }

    # This is the first function that runs, it runs once at the beginning of the entire strategy run
    def initialize(self) -> None:
        # Run the strategy heartbeat once per trading day.
        self.sleeptime = "1D"

        # The draft book is stateful across the whole strategy run: created
        # empty here, seeded and shaped by build_portfolio, read by submission.
        self.portfolio = Portfolio()

        # Each finalized portfolio has one entry order per symbol. Registering
        # this map before submission lets an immediate market fill find its row.
        self.trade_ids_by_symbol: dict[str, str] = {}

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

    def on_trading_iteration(self) -> None:
        """Log the daily strategy heartbeat."""
        log.info("CSF Champions daily trading iteration")

    def on_filled_order(
        self,
        position: Position,
        order: Order,
        price: float,
        quantity: float,
        multiplier: float,
    ) -> None:
        """Close the ledger row and idea when one market order fully fills."""
        if self.is_backtesting:
            return

        trade_id = self.trade_ids_by_symbol.get(order.asset.symbol)

        if trade_id is None:
            log.warning(
                "%s: filled order %s has no trade-ledger row",
                order.asset.symbol,
                order.identifier,
            )
            return

        idea_id = complete_order(
            STRATEGY,
            trade_id,
            average_fill_price=float(order.avg_fill_price or price),
            filled_at=self.get_datetime(),
        )
        update_idea_status(STRATEGY, idea_id, "filled")
        log.info("%s: market order filled - idea marked filled", order.asset.symbol)
