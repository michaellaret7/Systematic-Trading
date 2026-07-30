"""Broker ↔ Dynamo portfolio sync shared by all strategies.

Fill path owns quantity / side / cost for one ``(strategy, symbol)`` row.
Mark path is observational only: stamps Alpaca unrealized P&L onto rows that
already exist. Strategy adapters pass their registry name so one account can
host multiple sleeves.
"""

from datetime import datetime
from math import isfinite
from typing import Any

from systematic_trading.data.repository import (
    apply_broker_position,
    delete_position,
    load_positions,
    update_marks,
)
from systematic_trading.domain.portfolio import PositionMarks, PositionSide
from systematic_trading.logging_setup import get_logger

log = get_logger(__name__)


#     ================================
# --> Helper funcs
#     ================================


def position_side(broker_position: Any, signed_qty: float) -> PositionSide:
    """Map a Lumibot/Alpaca position side onto the portfolio domain side."""
    raw = getattr(broker_position, "side", None)
    value = str(getattr(raw, "value", raw) or "").strip().lower()

    if value == "long" or value == "short":
        return value

    return "short" if signed_qty < 0 else "long"


def alpaca_positions_by_symbol(strategy: Any) -> dict[str, Any]:
    """Open Alpaca positions keyed by uppercase symbol.

    Uses the raw TradingClient so mark fields Lumibot drops (e.g.
    ``unrealized_plpc``) are available.
    """
    api = getattr(getattr(strategy, "broker", None), "api", None)

    if api is None or not hasattr(api, "get_all_positions"):
        log.warning("broker.api unavailable - skipping position mark sync")
        return {}

    return {str(pos.symbol).strip().upper(): pos for pos in api.get_all_positions()}


def sync_portfolio_from_fill(
    strategy_name: str,
    broker_position: Any | None,
    *,
    symbol: str,
    filled_at: datetime,
    idea_id: str | None = None,
) -> None:
    """Upsert or delete one strategy-owned portfolio row after a broker fill.

    Quantity is always stored as a positive whole-share count; shorts use
    ``side="short"`` rather than a negative quantity.
    """
    signed_qty = float(getattr(broker_position, "quantity", 0) or 0) if broker_position else 0.0
    quantity = int(abs(signed_qty))

    if broker_position is None or quantity <= 0:
        delete_position(strategy_name, symbol)
        log.info("%s: flat at broker - portfolio row removed", symbol)
        return

    avg_cost = float(getattr(broker_position, "avg_fill_price", 0) or 0)

    if not isfinite(avg_cost) or avg_cost <= 0:
        log.warning("%s: filled but avg_fill_price missing - portfolio not updated", symbol)
        return

    side = position_side(broker_position, signed_qty)

    apply_broker_position(
        strategy_name,
        symbol,
        quantity=quantity,
        side=side,
        avg_cost=avg_cost,
        now=filled_at,
        idea_id=idea_id,
    )
    log.info("%s: portfolio upserted qty=%s side=%s", symbol, quantity, side)


def sync_position_marks(strategy: Any, strategy_name: str) -> None:
    """Stamp Alpaca unrealized marks onto one sleeve's Dynamo portfolio rows."""
    book = load_positions(strategy_name)

    if book.empty:
        return

    broker_by_symbol = alpaca_positions_by_symbol(strategy)

    if not broker_by_symbol:
        return

    now = strategy.get_datetime()
    updated = 0

    for row in book.to_dict(orient="records"):
        symbol = str(row["symbol"]).strip().upper()
        alpaca_pos = broker_by_symbol.get(symbol)

        if alpaca_pos is None:
            log.warning("%s: in portfolio table but flat at broker", symbol)
            continue

        current_price = float(getattr(alpaca_pos, "current_price", 0) or 0)

        if not isfinite(current_price) or current_price <= 0:
            log.warning("%s: broker mark missing current_price - skipping", symbol)
            continue

        update_marks(
            PositionMarks(
                strategy=strategy_name,
                symbol=symbol,
                unrealized_pl=float(getattr(alpaca_pos, "unrealized_pl", 0) or 0),
                unrealized_plpc=float(getattr(alpaca_pos, "unrealized_plpc", 0) or 0),
                current_price=current_price,
                market_value=float(getattr(alpaca_pos, "market_value", 0) or 0),
                mark_synced_at=now,
            )
        )
        updated += 1

    log.info(
        "Synced marks for %s/%s portfolio positions (%s)",
        updated,
        len(book),
        strategy_name,
    )
