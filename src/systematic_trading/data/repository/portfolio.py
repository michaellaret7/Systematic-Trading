"""DynamoDB portfolio: one open position per (strategy, symbol).

The fill path owns quantity, side, and cost. Mark columns are observational
and updated by a separate sync (strategy iteration or a seed job). Flat
positions are deleted rather than stored at zero.
"""

from datetime import datetime
from decimal import Decimal

import pandas as pd
from boto3.dynamodb.conditions import Key

from systematic_trading.config import is_paper
from systematic_trading.data.repository.dynamo import get_table, query_all, scan_all
from systematic_trading.domain.portfolio import Position, PositionMarks, PositionSide

TABLE_NAME = "portfolio"


def upsert_position(position: Position) -> None:
    """Write book fields for one open position without clearing mark columns.

    ``opened_at`` and ``idea_id`` stick on first write via ``if_not_exists`` so
    later fills can resize the row without erasing seed/open history or marks.
    """
    update_expression = (
        "SET #side = :side, quantity = :q, avg_cost = :c, updated_at = :u, "
        "paper = :p, opened_at = if_not_exists(opened_at, :o)"
    )
    values: dict = {
        ":side": position.side,
        ":q": Decimal(str(position.quantity)),
        ":c": Decimal(str(position.avg_cost)),
        ":u": position.updated_at.isoformat(),
        ":p": is_paper(),
        ":o": position.opened_at.isoformat(),
    }

    if position.idea_id is not None:
        update_expression += ", idea_id = if_not_exists(idea_id, :idea)"
        values[":idea"] = position.idea_id

    get_table(TABLE_NAME).update_item(
        Key={"strategy": position.strategy, "symbol": position.symbol},
        UpdateExpression=update_expression,
        ExpressionAttributeNames={"#side": "side"},
        ExpressionAttributeValues=values,
    )


def delete_position(strategy: str, symbol: str) -> None:
    """Remove one position row (position is flat at the broker)."""
    get_table(TABLE_NAME).delete_item(Key={"strategy": strategy, "symbol": symbol})


def apply_broker_position(
    strategy: str,
    symbol: str,
    *,
    quantity: float,
    side: PositionSide,
    avg_cost: float,
    now: datetime,
    idea_id: str | None = None,
) -> None:
    """Sync one strategy-owned symbol to the post-fill broker size.

    ``quantity <= 0`` deletes the row (flat). Otherwise validates through
    ``Position`` and upserts book fields. Quantity may be fractional (crypto).
    """
    symbol = symbol.strip().upper()

    if quantity <= 0:
        delete_position(strategy, symbol)
        return

    upsert_position(
        Position(
            strategy=strategy,
            symbol=symbol,
            side=side,
            quantity=quantity,
            avg_cost=avg_cost,
            opened_at=now,
            updated_at=now,
            idea_id=idea_id,
        )
    )


def update_marks(marks: PositionMarks) -> None:
    """Overwrite observational mark columns on an existing portfolio row."""
    get_table(TABLE_NAME).update_item(
        Key={"strategy": marks.strategy, "symbol": marks.symbol},
        UpdateExpression=(
            "SET unrealized_pl = :pl, unrealized_plpc = :plpc, "
            "current_price = :px, market_value = :mv, mark_synced_at = :t"
        ),
        ExpressionAttributeValues={
            ":pl": Decimal(str(marks.unrealized_pl)),
            ":plpc": Decimal(str(marks.unrealized_plpc)),
            ":px": Decimal(str(marks.current_price)),
            ":mv": Decimal(str(marks.market_value)),
            ":t": marks.mark_synced_at.isoformat(),
        },
    )


def load_positions(strategy: str | None = None) -> pd.DataFrame:
    """Open positions for one strategy, or the whole table when omitted."""
    table = get_table(TABLE_NAME)
    items = (
        scan_all(table)
        if strategy is None
        else query_all(table, Key("strategy").eq(strategy))
    )

    return pd.DataFrame(items)


def seed_position(position: Position, marks: PositionMarks) -> None:
    """Bootstrap one row with book fields and Alpaca marks in a single write.

    Used by the one-time Alpaca seed script so existing broker holdings land in
    Dynamo without re-running portfolio construction. Not the live fill path.
    """
    if (
        marks.strategy != position.strategy
        or marks.symbol != position.symbol
    ):
        raise ValueError("position and marks must share strategy and symbol")

    item: dict = {
        "strategy": position.strategy,
        "symbol": position.symbol,
        "side": position.side,
        "quantity": Decimal(str(position.quantity)),
        "avg_cost": Decimal(str(position.avg_cost)),
        "opened_at": position.opened_at.isoformat(),
        "updated_at": position.updated_at.isoformat(),
        "paper": is_paper(),
        "unrealized_pl": Decimal(str(marks.unrealized_pl)),
        "unrealized_plpc": Decimal(str(marks.unrealized_plpc)),
        "current_price": Decimal(str(marks.current_price)),
        "market_value": Decimal(str(marks.market_value)),
        "mark_synced_at": marks.mark_synced_at.isoformat(),
    }

    if position.idea_id is not None:
        item["idea_id"] = position.idea_id

    get_table(TABLE_NAME).put_item(Item=item)


if __name__ == "__main__":
    x = load_positions()
    # print(x.loc[(x["strategy"] == "btc_ticker") & (x["unrealized_pl"] > 0)])
    print(x)
