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
    complete_order,
    delete_position,
    load_positions,
    update_idea_status,
    update_marks,
)
from systematic_trading.domain.portfolio import PositionMarks, PositionSide
from systematic_trading.logging_setup import get_logger

log = get_logger(__name__)

# Alpaca crypto pairs are BASE+QUOTE with no separator (e.g. BTCUSD). Our book
# stores the base (BTC). Strip these quotes when indexing broker positions.
_CRYPTO_QUOTE_SUFFIXES = ("USDT", "USDC", "USD")


#     ================================
# --> Helper funcs
#     ================================


def normalize_symbol(symbol: str) -> str:
    """Normalize a broker or book symbol for portfolio keys.

    Equities stay as-is (uppercased). Crypto pairs like ``BTCUSD`` collapse to
    the base asset ``BTC`` so fill rows and Alpaca marks join.
    """
    raw = symbol.strip().upper()

    for quote in _CRYPTO_QUOTE_SUFFIXES:
        if raw.endswith(quote) and len(raw) > len(quote):
            base = raw[: -len(quote)]

            # Crypto bases are short tickers (BTC, ETH, SOL, …), not equity roots.
            if 2 <= len(base) <= 5 and base.isalpha():
                return base

    return raw


def position_side(broker_position: Any, signed_qty: float) -> PositionSide:
    """Map a Lumibot/Alpaca position side onto the portfolio domain side."""
    raw = getattr(broker_position, "side", None)
    value = str(getattr(raw, "value", raw) or "").strip().lower()

    if value == "long" or value == "short":
        return value

    return "short" if signed_qty < 0 else "long"


def alpaca_positions_by_symbol(strategy: Any) -> dict[str, Any]:
    """Open Alpaca positions keyed by normalized uppercase symbol.

    Uses the raw TradingClient so mark fields Lumibot drops (e.g.
    ``unrealized_plpc``) are available. Crypto pairs are indexed under both the
    raw symbol (``BTCUSD``) and the base (``BTC``).
    """
    api = getattr(getattr(strategy, "broker", None), "api", None)

    if api is None or not hasattr(api, "get_all_positions"):
        log.warning("broker.api unavailable - skipping position mark sync")
        return {}

    by_symbol: dict[str, Any] = {}

    for pos in api.get_all_positions():
        raw = str(pos.symbol).strip().upper()
        base = normalize_symbol(raw)
        by_symbol[raw] = pos
        by_symbol[base] = pos

    return by_symbol


def finalize_filled_trade(
    strategy_name: str,
    trade_id: str,
    *,
    symbol: str,
    average_fill_price: float,
    filled_at: datetime,
    broker_position: Any | None,
) -> str | None:
    """Close the ledger row, mark the idea filled when linked, sync portfolio.

    Shared by live fill hooks and the reconcile pass so both paths stay
    identical. Returns the idea_id when one was linked.
    """
    idea_id = complete_order(
        strategy_name,
        trade_id,
        average_fill_price=average_fill_price,
        filled_at=filled_at,
    )

    if idea_id is not None:
        update_idea_status(strategy_name, idea_id, "filled")

    sync_portfolio_from_fill(
        strategy_name,
        broker_position,
        symbol=symbol,
        idea_id=idea_id,
        filled_at=filled_at,
    )

    return idea_id


def sync_portfolio_from_fill(
    strategy_name: str,
    broker_position: Any | None,
    *,
    symbol: str,
    filled_at: datetime,
    idea_id: str | None = None,
) -> None:
    """Upsert or delete one strategy-owned portfolio row after a broker fill.

    Quantity is stored as a positive size (whole shares or fractional crypto);
    shorts use ``side="short"`` rather than a negative quantity. Symbols are
    normalized so crypto pairs land under the base ticker.
    """
    symbol = normalize_symbol(symbol)
    signed_qty = float(getattr(broker_position, "quantity", 0) or 0) if broker_position else 0.0
    quantity = abs(signed_qty)

    if broker_position is None or not isfinite(quantity) or quantity <= 0:
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


def sync_position_pnl(strategy: Any, strategy_name: str) -> None:
    """Stamp Alpaca unrealized P&L marks onto one sleeve's Dynamo portfolio rows.

    Joins the strategy book to broker positions by normalized symbol so equity
    tickers and crypto bases (``BTC`` ↔ ``BTCUSD``) both resolve.
    """
    book = load_positions(strategy_name)

    if book.empty:
        return

    broker_by_symbol = alpaca_positions_by_symbol(strategy)

    if not broker_by_symbol:
        return

    now = strategy.get_datetime()
    updated = 0

    for row in book.to_dict(orient="records"):
        symbol = normalize_symbol(str(row["symbol"]))
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
        "Synced position PnL for %s/%s portfolio positions (%s)",
        updated,
        len(book),
        strategy_name,
    )
