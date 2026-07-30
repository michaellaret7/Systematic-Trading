"""Seed the DynamoDB portfolio table from current Alpaca open positions.

One-time bootstrap for an account that already holds positions so you do not
need to re-run portfolio construction. Assigns every open broker position to
one strategy (default: csf_champions) under the one-owner-per-symbol rule.

Writes book fields (qty, side, avg cost) and the current Alpaca marks
(unrealized P&L, price). Does not place or cancel orders. ``opened_at`` is
the seed time — Alpaca does not expose the original open timestamp on the
position object.

Paper/live follows ``ALPACA_PAPER`` (paper by default).

Usage:
    uv run python scripts/seed_portfolio_from_alpaca.py
    uv run python scripts/seed_portfolio_from_alpaca.py csf_champions
    uv run python scripts/seed_portfolio_from_alpaca.py csf_champions --yes
    uv run python scripts/seed_portfolio_from_alpaca.py csf_champions --dry-run
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal

from alpaca.trading.client import TradingClient

from systematic_trading.config import alpaca_config, is_paper
from systematic_trading.data.repository.portfolio import TABLE_NAME, seed_position
from systematic_trading.domain.portfolio import Position, PositionMarks, PositionSide

DEFAULT_STRATEGY = "csf_champions"


#     ================================
# --> Helper funcs
#     ================================


def _broker_client() -> TradingClient:
    """Alpaca trading client, paper/live per ``ALPACA_PAPER``."""
    config = alpaca_config()

    return TradingClient(
        api_key=config["API_KEY"],
        secret_key=config["API_SECRET"],
        paper=config["PAPER"],
    )


def _whole_quantity(raw_qty: object, symbol: str) -> int | None:
    """Positive whole-share quantity, or None if fractional / empty."""
    qty = abs(Decimal(str(raw_qty)))

    if qty <= 0:
        return None

    if qty != qty.to_integral_value():
        print(f"  skip {symbol}: fractional qty {qty} (whole shares only)")
        return None

    return int(qty)


def _position_side(raw_side: object, symbol: str) -> PositionSide | None:
    """Map Alpaca side (string or enum) to our domain side."""
    value = getattr(raw_side, "value", raw_side)
    side = str(value).strip().lower()

    if side == "long" or side == "short":
        return side

    print(f"  skip {symbol}: unknown side {raw_side!r}")
    return None


def _records_from_alpaca(
    strategy: str,
    broker_positions: list,
    now: datetime,
) -> list[tuple[Position, PositionMarks]]:
    """Convert Alpaca position objects into domain records."""
    records: list[tuple[Position, PositionMarks]] = []

    for pos in broker_positions:
        symbol = str(pos.symbol).strip().upper()
        quantity = _whole_quantity(pos.qty, symbol)
        side = _position_side(pos.side, symbol)

        if quantity is None or side is None:
            continue

        avg_cost = float(pos.avg_entry_price)
        current_price = float(pos.current_price)

        if avg_cost <= 0 or current_price <= 0:
            print(f"  skip {symbol}: non-positive price (avg={avg_cost}, last={current_price})")
            continue

        position = Position(
            strategy=strategy,
            symbol=symbol,
            side=side,
            quantity=quantity,
            avg_cost=avg_cost,
            opened_at=now,
            updated_at=now,
            idea_id=None,
        )
        marks = PositionMarks(
            strategy=strategy,
            symbol=symbol,
            unrealized_pl=float(pos.unrealized_pl),
            unrealized_plpc=float(pos.unrealized_plpc),
            current_price=current_price,
            market_value=float(pos.market_value),
            mark_synced_at=now,
        )
        records.append((position, marks))

    return records


def _confirm(strategy: str, records: list[tuple[Position, PositionMarks]]) -> bool:
    """Show the seed plan and require a typed confirmation."""
    mode = "PAPER" if is_paper() else "LIVE"

    print(f"Seed {TABLE_NAME} from Alpaca ({mode})")
    print(f"  strategy: {strategy}")
    print(f"  positions: {len(records)}")

    for position, marks in records:
        print(
            f"    {position.symbol:<6} {position.side:<5} "
            f"qty={position.quantity:<6} avg=${position.avg_cost:,.2f}  "
            f"unrealized={marks.unrealized_plpc:.2%}"
        )

    print("  note: opened_at is seed time; idea_id is left empty")
    print("  this overwrites any existing row for the same (strategy, symbol)")

    return input("Proceed? type 'yes' to confirm: ").strip().lower() == "yes"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "strategy",
        nargs="?",
        default=DEFAULT_STRATEGY,
        help=f"strategy partition key (default: {DEFAULT_STRATEGY})",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip the confirmation prompt",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list positions that would be written without writing",
    )

    return parser.parse_args()


#     ================================
# --> Entry point
#     ================================


def main() -> None:
    args = parse_args()
    strategy = args.strategy.strip()

    if not strategy:
        raise SystemExit("strategy must not be empty")

    client = _broker_client()
    broker_positions = list(client.get_all_positions())

    if not broker_positions:
        print("Alpaca has no open positions — nothing to seed.")
        return

    now = datetime.now(timezone.utc)
    records = _records_from_alpaca(strategy, broker_positions, now)

    if not records:
        print("No seedable whole-share positions found.")
        return

    if args.dry_run:
        mode = "PAPER" if is_paper() else "LIVE"
        print(f"Dry run — would seed {len(records)} rows into {TABLE_NAME} ({mode}):")
        for position, marks in records:
            print(
                f"  {position.symbol:<6} {position.side:<5} "
                f"qty={position.quantity:<6} avg=${position.avg_cost:,.2f}  "
                f"unrealized={marks.unrealized_plpc:.2%}"
            )
        return

    if not args.yes and not _confirm(strategy, records):
        print("Aborted.")
        return

    for position, marks in records:
        seed_position(position, marks)

    print(f"Seeded {len(records)} positions into {TABLE_NAME} for {strategy}.")


if __name__ == "__main__":
    main()
