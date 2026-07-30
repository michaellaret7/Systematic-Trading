"""DynamoDB portfolio: one open position per (strategy, symbol).

The fill path owns quantity, side, and cost. Mark columns are observational
and updated by a separate sync (strategy iteration or a seed job). Flat
positions are deleted rather than stored at zero.
"""

from decimal import Decimal

import pandas as pd
from boto3.dynamodb.conditions import Key

from systematic_trading.config import is_paper
from systematic_trading.data.repository.dynamo import get_table, query_all, scan_all
from systematic_trading.domain.portfolio import Position, PositionMarks

TABLE_NAME = "portfolio"


def upsert_position(position: Position) -> None:
    """Write or overwrite one open position's book fields."""
    item: dict = {
        "strategy": position.strategy,
        "symbol": position.symbol,
        "side": position.side,
        "quantity": position.quantity,
        "avg_cost": Decimal(str(position.avg_cost)),
        "opened_at": position.opened_at.isoformat(),
        "updated_at": position.updated_at.isoformat(),
        "paper": is_paper(),
    }

    if position.idea_id is not None:
        item["idea_id"] = position.idea_id

    get_table(TABLE_NAME).put_item(Item=item)


def delete_position(strategy: str, symbol: str) -> None:
    """Remove one position row (position is flat at the broker)."""
    get_table(TABLE_NAME).delete_item(Key={"strategy": strategy, "symbol": symbol})


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
        "quantity": position.quantity,
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
    print(x.loc[(x["strategy"] == "csf_champions") & (x["unrealized_pl"] > 0)])
