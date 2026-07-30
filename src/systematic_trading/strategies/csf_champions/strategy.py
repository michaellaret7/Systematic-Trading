"""Lumibot adapter for the CSF Champions strategy.

Startup pipeline (runs once in ``initialize``, gated by ``build_portfolio``):
generate trade ideas (only when ``generate_ideas`` is True), build the draft
portfolio via the portfolio-constructor agent, then submit the book as
whole-share market buys.

Each fully-filled broker order closes its trade-ledger row, marks its source
idea filled, and syncs the strategy-owned portfolio row. Because Lumibot drops
fill events on the first iteration, every live iteration also reconciles open
ledger rows against the broker. Marks refresh on the same cadence.
"""

from lumibot.entities import Order, Position
from lumibot.strategies import Strategy

from systematic_trading.logging_setup import get_logger
from systematic_trading.portfolio import (
    finalize_filled_trade,
    reconcile_open_orders,
    sync_position_pnl,
)
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


class CsfChampions(Strategy):
    """CSF Champions: agent-scored fundamentals book, long-only sleeve."""

    WARM_UP_TRADING_DAYS = 0

    parameters = {
        "generate_ideas": False,
        "build_portfolio": False,
    }

    # This is the first function that runs, it runs once at the beginning of the entire strategy run
    def initialize(self) -> None:
        # Run the strategy heartbeat once per trading day.
        self.sleeptime = "1D"

        # The draft book is stateful across the whole strategy run: created
        # empty here, seeded and shaped by build_portfolio, read by submission.
        self.portfolio = Portfolio()

        # In-session maps so fill hooks resolve ledger rows quickly. Durable
        # recovery uses ledger.broker_order_id + reconcile_open_orders.
        self.trade_ids_by_symbol: dict[str, str] = {}
        self.trade_ids_by_order_id: dict[str, str] = {}

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
        """Daily heartbeat: reconcile missed fills, then refresh marks."""
        log.info("CSF Champions daily trading iteration")

        if self.is_backtesting:
            return

        # Close ledger rows whose broker fills were dropped at startup / restart.
        reconcile_open_orders(self, STRATEGY)
        sync_position_pnl(self, STRATEGY)

    def on_filled_order(
        self,
        position: Position,
        order: Order,
        price: float,
        quantity: float,
        multiplier: float,
    ) -> None:
        """Close ledger + idea, then sync the strategy portfolio book."""
        if self.is_backtesting:
            return

        symbol = order.asset.symbol
        order_id = str(order.identifier) if order.identifier is not None else ""
        trade_id = self.trade_ids_by_order_id.get(order_id) or self.trade_ids_by_symbol.get(
            symbol
        )

        if trade_id is None:
            log.warning(
                "%s: filled order %s has no trade-ledger row (will rely on reconcile)",
                symbol,
                order.identifier,
            )
            return

        filled_at = self.get_datetime()
        finalize_filled_trade(
            STRATEGY,
            trade_id,
            symbol=symbol,
            average_fill_price=float(order.avg_fill_price or price),
            filled_at=filled_at,
            broker_position=position,
        )

        if order_id:
            self.trade_ids_by_order_id.pop(order_id, None)

        log.info("%s: market order filled - ledger and portfolio updated", symbol)
