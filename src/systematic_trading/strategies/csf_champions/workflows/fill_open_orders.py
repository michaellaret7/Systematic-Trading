"""Reconcile open ledger orders against broker truth, then re-submit remainders.

Runs every trading iteration. The fill hooks are best-effort: Lumibot silently
drops trade events processed during a session's first iteration, so the ledger
can lag the broker. This sweep treats the broker position as the truth for
each open row — healing missed fills (closing rows and flipping ideas to
``filled`` when the target is already held) before deciding what remainder, if
any, still needs a fresh DAY limit buy at today's price.

The working-order check uses Lumibot's local order tracking, never the
broker's order-list endpoint: Alpaca's list lags a few seconds behind fresh
submissions, and trusting it once produced 39 duplicate orders seconds after
the entries went out.

Assumes this sleeve runs one entry campaign per symbol, so the broker position
quantity for a symbol is exactly what its ledger row has filled.
"""

from lumibot.entities import Order
from lumibot.strategies import Strategy

from systematic_trading.data.repository import load_open_orders, sync_fill, update_idea_status
from systematic_trading.logging_setup import get_logger
from systematic_trading.strategies.csf_champions.workflows.enter_positions import (
    STRATEGY,
    consolidated_prices,
    entry_base_price,
    entry_limit_price,
)

log = get_logger(__name__)


#     ================================
# --> Helper funcs
#     ================================


def working_buy_symbols(strategy: Strategy) -> set[str]:
    """Symbols with an active buy order in local tracking right now.

    ``broker_refresh=False`` is deliberate: local tracking knows just-submitted
    orders instantly, while Alpaca's order-list endpoint lags behind them.
    """
    orders = strategy.get_orders(statuses=Order.ACTIVE_STATUSES, broker_refresh=False)

    return {order.asset.symbol for order in orders if order.is_buy_order()}


def reconcile_row(strategy: Strategy, row: dict) -> int:
    """Heal one open row from the broker position; returns true filled quantity.

    If the broker holds more than the ledger recorded, the row is overwritten
    with the position's quantity and average entry price; a row healed to its
    target is closed and its idea flipped to ``filled``.
    """
    recorded = int(row["filled_quantity"])
    position = strategy.get_position(row["symbol"])

    if position is None:
        return recorded

    position_qty = int(float(position.quantity))

    if position_qty <= recorded:
        return recorded

    avg_price = float(position.avg_fill_price) if position.avg_fill_price else 0.0

    if avg_price <= 0:
        log.warning(
            "%s: position %d exceeds recorded %d but has no average price — not healing",
            row["symbol"],
            position_qty,
            recorded,
        )
        return recorded

    completed_idea = sync_fill(
        STRATEGY, row["trade_id"], position_qty, avg_price, strategy.get_datetime()
    )

    log.info(
        "%s: healed ledger from broker — %d -> %d/%d @ avg $%.2f",
        row["symbol"],
        recorded,
        position_qty,
        int(row["target_quantity"]),
        avg_price,
    )

    if completed_idea:
        update_idea_status(STRATEGY, completed_idea, "filled")

    return position_qty


def resubmit_remainder(strategy: Strategy, row: dict, remainder: int, anchor: float | None) -> bool:
    """Submit a fresh DAY limit buy for one open row's remainder; True if sent."""
    symbol = row["symbol"]

    base_price = entry_base_price(strategy, symbol, anchor)

    if base_price is None:
        log.warning("%s: no price available — leaving remainder for tomorrow", symbol)
        return False

    limit_price = entry_limit_price(base_price)

    if limit_price <= 0:
        log.warning("%s: computed limit price is not positive — skipping", symbol)
        return False

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
    """Heal open ledger rows from broker positions, then re-submit remainders."""
    open_orders = load_open_orders(STRATEGY)

    if open_orders.empty:
        return

    working = working_buy_symbols(strategy)
    healed_closed = 0
    resubmitted = 0

    # One batched call up front; most rows will not need it, but a single round
    # trip is cheaper than deciding per row.
    anchors = consolidated_prices(list(open_orders["symbol"]))

    for row in open_orders.to_dict("records"):
        true_filled = reconcile_row(strategy, row)

        remainder = int(row["target_quantity"]) - true_filled

        if remainder <= 0:
            healed_closed += 1
            continue

        if row["symbol"] in working:
            log.info("%s: buy order already working — skipping", row["symbol"])
            continue

        if resubmit_remainder(strategy, row, remainder, anchors.get(row["symbol"])):
            resubmitted += 1

    log.info(
        "Open-order sweep: %d open, %d healed closed, %d re-submitted",
        len(open_orders),
        healed_closed,
        resubmitted,
    )
