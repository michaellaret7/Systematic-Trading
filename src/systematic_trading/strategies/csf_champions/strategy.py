"""Lumibot adapter for the CSF Champions strategy.

Startup pipeline (runs once in ``initialize``, gated by ``build_portfolio``):
generate trade ideas (only when ``generate_ideas`` is True), build the draft
portfolio via the portfolio-constructor agent, then submit the book as
whole-share limit buys.

Daily loop: re-submit the unfilled remainder of open ledger orders. Broker
fill events accumulate into the ledger via the fill hooks, and an idea is
marked ``filled`` the moment its order reaches its target quantity.
"""

from lumibot.entities import Order, Position
from lumibot.strategies import Strategy

from systematic_trading.data.repository import apply_fill, update_idea_status
from systematic_trading.logging_setup import get_logger
from systematic_trading.strategies.csf_champions.portfolio import Portfolio
from systematic_trading.strategies.csf_champions.workflows.build_portfolio import (
    construct_portfolio,
)
from systematic_trading.strategies.csf_champions.workflows.enter_positions import (
    STRATEGY,
    enter_positions,
)
from systematic_trading.strategies.csf_champions.workflows.fill_open_orders import (
    fill_open_orders,
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
        "build_portfolio": True,
    }

    # This is the first function that runs, it runs once at the beginning of the entire strategy run
    def initialize(self) -> None:
        self.sleeptime = "1D"

        # The draft book is stateful across the whole strategy run: created
        # empty here, seeded and shaped by build_portfolio, read by submission.
        self.portfolio = Portfolio()

        # Broker order id -> ledger trade_id, so fill events find their row.
        # In-memory only: a restart loses it, and untracked fills are then
        # reconciled by the next morning's open-order sweep.
        self.order_trade_ids: dict[str, str] = {}

        # The flag is the single switch: only run the startup pipeline
        # (idea generation, construction, submission) when explicitly asked.
        if not self.parameters["build_portfolio"]:
            log.info("build_portfolio is off — skipping startup pipeline")
            return

        if self.parameters["generate_ideas"]:
            log.info("Generating trade ideas")
            generate_trade_ideas()
        else:
            log.info("Using existing trade ideas from DynamoDB")

        construct_portfolio(self.portfolio)

        # Push the finalized draft book to the broker as whole-share limit buys.
        enter_positions(self, self.portfolio)

    def on_trading_iteration(self) -> None:
        if self.is_backtesting:
            return

        # Yesterday's DAY orders died at the close; re-submit any remainder.
        # This runs in the morning after the close.
        fill_open_orders(self)

    def _apply_order_fill(self, order: Order, price: float, quantity: float) -> None:
        """Fold one broker fill into the ledger; flip the idea when complete."""
        trade_id = self.order_trade_ids.get(order.identifier)

        if trade_id is None:
            log.warning(
                "%s: fill for untracked order %s — ledger not updated (sweep reconciles tomorrow)",
                order.asset.symbol,
                order.identifier,
            )
            return

        completed_idea = apply_fill(
            STRATEGY, trade_id, int(quantity), float(price), self.get_datetime()
        )

        if completed_idea:
            update_idea_status(STRATEGY, completed_idea, "filled")
            log.info("%s: target reached — idea marked filled", order.asset.symbol)

    def on_partially_filled_order(
        self, position: Position, order: Order, price: float, quantity: float, multiplier: float
    ) -> None:

        if self.is_backtesting:
            return

        self._apply_order_fill(order, price, quantity)

    def on_filled_order(
        self, position: Position, order: Order, price: float, quantity: float, multiplier: float
    ) -> None:

        if self.is_backtesting:
            return

        self._apply_order_fill(order, price, quantity)
