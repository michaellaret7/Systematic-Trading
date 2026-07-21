"""Re-submit the unfilled remainder of open ledger orders.

Runs at the start of each trading day. Yesterday's DAY limit orders died at
the close, so any ledger row still missing ``filled_at`` gets a fresh
marketable DAY limit buy for the remaining shares, re-priced from today's
quote but still capped at the analyst's max entry price. The new broker order
is mapped to the same ledger row, so fills keep accumulating against the
original target until it is reached.

A row whose symbol already has a working buy order at the broker is skipped —
that order is still doing the job.
"""

from lumibot.entities import Order
from lumibot.strategies import Strategy

from systematic_trading.data.repository import load_open_orders
from systematic_trading.logging_setup import get_logger
from systematic_trading.strategies.csf_champions.workflows.enter_positions import (
    STRATEGY,
    entry_base_price,
    entry_limit_price,
)

log = get_logger(__name__)


#     ================================
# --> Helper funcs
#     ================================


def working_buy_symbols(strategy: Strategy) -> set[str]:
    """Symbols with an active buy order at the broker right now."""
    orders = strategy.get_orders(statuses=Order.ACTIVE_STATUSES)

    return {order.asset.symbol for order in orders if order.is_buy_order()}


def resubmit_remainder(strategy: Strategy, row: dict) -> bool:
    """Submit a fresh DAY limit buy for one open row's remainder; True if sent."""
    symbol = row["symbol"]
    remainder = int(row["target_quantity"]) - int(row["filled_quantity"])

    base_price = entry_base_price(strategy, symbol)

    if base_price is None:
        log.warning("%s: no price available — leaving remainder for tomorrow", symbol)
        return False

    limit_price = entry_limit_price(base_price, float(row["max_entry_price"]))

    order = strategy.create_order(
        symbol, remainder, "buy", limit_price=limit_price, time_in_force="day"
    )

    strategy.submit_order(order)

    strategy.order_trade_ids[order.identifier] = row["trade_id"]

    log.info(
        "%s: re-submitted remainder %d/%d @ limit $%.2f",
        symbol,
        remainder,
        int(row["target_quantity"]),
        limit_price,
    )

    return True


def fill_open_orders(strategy: Strategy) -> None:
    """Re-submit every open ledger order's remainder as a fresh DAY limit buy."""
    open_orders = load_open_orders(STRATEGY)

    if open_orders.empty:
        return

    working = working_buy_symbols(strategy)
    resubmitted = 0

    for row in open_orders.to_dict("records"):
        if row["symbol"] in working:
            log.info("%s: buy order already working at the broker — skipping", row["symbol"])
            continue

        if resubmit_remainder(strategy, row):
            resubmitted += 1

    log.info("Open-order sweep: %d open, %d re-submitted", len(open_orders), resubmitted)
