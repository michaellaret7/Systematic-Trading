"""Reconcile open ledger rows against the broker.

Lumibot drops fill events while ``_first_iteration`` is true, so market orders
submitted in ``initialize`` often never hit ``on_filled_order``. This pass
closes those rows from broker truth and also recovers after process restarts
when the in-memory order-id map is gone.

Prefer ``broker_order_id`` on the ledger row. When missing (legacy rows), fall
back to matching a closed broker order by symbol + side.
"""

from datetime import datetime
from math import isfinite
from typing import Any

from systematic_trading.data.repository import load_open_orders
from systematic_trading.logging_setup import get_logger
from systematic_trading.portfolio.sync import finalize_filled_trade, normalize_symbol

log = get_logger(__name__)

_FILLED_STATUSES = frozenset(
    {
        "filled",
        "fill",
        "partially_filled",  # not complete; filtered by qty check below
        "partial_fill",
    }
)
_FULLY_FILLED_STATUSES = frozenset({"filled", "fill"})


#     ================================
# --> Helper funcs
#     ================================


def _status_value(raw: Any) -> str:
    """Normalize Alpaca/Lumibot order status to a lowercase string."""
    return str(getattr(raw, "value", raw) or "").strip().lower()


def _broker_api(strategy: Any) -> Any | None:
    """Raw TradingClient when available."""
    api = getattr(getattr(strategy, "broker", None), "api", None)

    return api if api is not None and hasattr(api, "get_order_by_id") else None


def _filled_avg_price(order: Any) -> float | None:
    """Average fill price from an Alpaca order object."""
    for attr in ("filled_avg_price", "avg_fill_price"):
        raw = getattr(order, attr, None)

        if raw is None or raw == "":
            continue

        price = float(raw)

        if isfinite(price) and price > 0:
            return price

    return None


def _filled_qty(order: Any) -> float:
    """Filled quantity from an Alpaca order object."""
    for attr in ("filled_qty", "quantity", "qty"):
        raw = getattr(order, attr, None)

        if raw is None or raw == "":
            continue

        qty = abs(float(raw))

        if isfinite(qty):
            return qty

    return 0.0


def _order_symbol(order: Any) -> str:
    """Normalized symbol from a broker order."""
    raw = getattr(order, "symbol", None) or getattr(getattr(order, "asset", None), "symbol", "")

    return normalize_symbol(str(raw))


def _order_side(order: Any) -> str:
    """Buy/sell side from a broker order."""
    raw = getattr(order, "side", "")
    value = str(getattr(raw, "value", raw) or "").strip().lower()

    return value


def _is_fully_filled(order: Any, target_quantity: float) -> bool:
    """True when the broker order is fully filled for our target size."""
    status = _status_value(getattr(order, "status", None))

    if status not in _FULLY_FILLED_STATUSES and status not in _FILLED_STATUSES:
        return False

    if status in _FULLY_FILLED_STATUSES:
        return _filled_avg_price(order) is not None

    # Partial statuses only count when filled qty covers the target.
    return _filled_qty(order) + 1e-12 >= float(target_quantity) and _filled_avg_price(order) is not None


def _fetch_order_by_id(api: Any, broker_order_id: str) -> Any | None:
    """Load one broker order, or None if missing."""
    try:
        return api.get_order_by_id(broker_order_id)
    except Exception as exc:  # noqa: BLE001 - broker SDK errors vary
        log.warning("broker order %s lookup failed: %s", broker_order_id, exc)
        return None


def _closed_orders_by_symbol(api: Any) -> dict[str, list[Any]]:
    """Closed broker orders grouped by normalized symbol (newest first)."""
    try:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        orders = list(
            api.get_orders(
                filter=GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=500)
            )
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("failed to list closed broker orders: %s", exc)
        return {}

    by_symbol: dict[str, list[Any]] = {}

    for order in orders:
        symbol = _order_symbol(order)
        by_symbol.setdefault(symbol, []).append(order)

    return by_symbol


def _match_closed_order(
    row: dict,
    closed_by_symbol: dict[str, list[Any]],
) -> Any | None:
    """Best-effort match for legacy ledger rows without broker_order_id."""
    symbol = normalize_symbol(str(row["symbol"]))
    side = str(row.get("side", "")).strip().lower()
    target = float(row["target_quantity"])
    candidates = closed_by_symbol.get(symbol, [])

    for order in candidates:
        if _order_side(order) != side:
            continue

        if _is_fully_filled(order, target):
            return order

    return None


def _broker_position(strategy: Any, symbol: str) -> Any | None:
    """Current strategy position for portfolio sync, if any."""
    get_position = getattr(strategy, "get_position", None)

    if get_position is None:
        return None

    try:
        return get_position(symbol)
    except Exception:  # noqa: BLE001
        return None


def reconcile_open_orders(strategy: Any, strategy_name: str) -> int:
    """Close open ledger rows that the broker already shows as filled.

    Returns the number of rows finalized this pass.
    """
    open_rows = load_open_orders(strategy_name)

    if not open_rows:
        return 0

    api = _broker_api(strategy)

    if api is None:
        log.warning("%s: no broker.api - skip ledger reconcile", strategy_name)
        return 0

    closed_by_symbol: dict[str, list[Any]] | None = None
    finalized = 0
    now = strategy.get_datetime()

    for row in open_rows:
        trade_id = str(row["trade_id"])
        symbol = normalize_symbol(str(row["symbol"]))
        target = float(row["target_quantity"])
        broker_order_id = row.get("broker_order_id")
        broker_order = None

        if broker_order_id:
            broker_order = _fetch_order_by_id(api, str(broker_order_id))
        else:
            if closed_by_symbol is None:
                closed_by_symbol = _closed_orders_by_symbol(api)

            broker_order = _match_closed_order(row, closed_by_symbol)

        if broker_order is None or not _is_fully_filled(broker_order, target):
            continue

        avg_price = _filled_avg_price(broker_order)

        if avg_price is None:
            continue

        filled_at_raw = getattr(broker_order, "filled_at", None) or getattr(
            broker_order, "updated_at", None
        )
        filled_at = filled_at_raw if isinstance(filled_at_raw, datetime) else now

        finalize_filled_trade(
            strategy_name,
            trade_id,
            symbol=symbol,
            average_fill_price=avg_price,
            filled_at=filled_at,
            broker_position=_broker_position(strategy, symbol),
        )
        finalized += 1
        log.info(
            "%s: reconciled filled ledger row %s @ %s",
            symbol,
            trade_id,
            avg_price,
        )

    if finalized:
        log.info(
            "Reconciled %s/%s open ledger orders for %s",
            finalized,
            len(open_rows),
            strategy_name,
        )

    return finalized
