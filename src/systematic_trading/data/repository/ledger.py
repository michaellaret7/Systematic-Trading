"""DynamoDB trade ledger: one item per market entry order.

Each item is created before broker submission with the full ``target_quantity``
and zero fills. A broker completion event closes the item with the order's full
quantity, average fill price, total cost, and fill timestamp.

Items are keyed by ``strategy`` (partition) and ``trade_id`` (sort);
``trade_id`` starts with the ISO submission timestamp so a query returns
orders in chronological order.

Strategies write from live/paper runs only, never from backtests (guard with
``self.is_backtesting``).
"""

from datetime import datetime
from decimal import Decimal
from math import isfinite
from typing import Any
from uuid import uuid4

import pandas as pd
from boto3.dynamodb.conditions import Key

from systematic_trading.config import is_paper
from systematic_trading.data.repository.dynamo import get_table, query_all, scan_all
from systematic_trading.domain.trades import TradeOrder

TABLE_NAME = "trade-ledger"


#     ================================
# --> Helper funcs
#     ================================


def _load_order(table: Any, strategy: str, trade_id: str) -> dict:
    """Fetch one ledger item, failing fast if the row does not exist."""
    item = table.get_item(
        Key={"strategy": strategy, "trade_id": trade_id},
        ConsistentRead=True,
    ).get("Item")

    if item is None:
        raise KeyError(f"no ledger order {trade_id!r} for strategy {strategy!r}")

    return item


def record_order(order: TradeOrder) -> str:
    """Create one market entry in the ledger; return its trade ID.

    ``submitted_at`` should come from the strategy clock
    (``self.get_datetime()``). The row is created before broker submission so
    a fast market fill can always find it. The paper/live flag is stamped
    automatically so paper orders can never be mistaken for real-money ones.
    """
    trade_id = f"{order.submitted_at.isoformat()}#{order.symbol}#{uuid4().hex[:8]}"

    get_table(TABLE_NAME).put_item(
        Item={
            "strategy": order.strategy,
            "trade_id": trade_id,
            "idea_id": order.idea_id,
            "symbol": order.symbol,
            "side": order.side,
            "target_quantity": order.target_quantity,
            "filled_quantity": 0,
            "filled_cost": Decimal("0"),
            "filled_price": None,
            "filled_at": None,
            "submitted_at": order.submitted_at.isoformat(),
            "paper": is_paper(),
        }
    )

    return trade_id


def complete_order(
    strategy: str,
    trade_id: str,
    average_fill_price: float,
    filled_at: datetime,
) -> str:
    """Close one ledger row from the broker's fully-filled order event."""
    if not isfinite(average_fill_price) or average_fill_price <= 0:
        raise ValueError("average_fill_price must be positive")

    table = get_table(TABLE_NAME)
    item = _load_order(table, strategy, trade_id)
    filled_quantity = int(item["target_quantity"])
    filled_price = Decimal(str(average_fill_price))

    table.update_item(
        Key={"strategy": strategy, "trade_id": trade_id},
        UpdateExpression=(
            "SET filled_quantity = :q, filled_cost = :c, "
            "filled_price = :p, filled_at = :t"
        ),
        ExpressionAttributeValues={
            ":q": filled_quantity,
            ":c": filled_price * filled_quantity,
            ":p": filled_price,
            ":t": filled_at.isoformat(),
        },
    )

    return str(item["idea_id"])


def load_trades(strategy: str | None = None) -> pd.DataFrame:
    """Recorded orders for one strategy, or the whole table when omitted.

    Follows DynamoDB pagination so the full history comes back regardless of
    size. Returns an empty frame if nothing matches.
    """
    table = get_table(TABLE_NAME)
    items = (
        scan_all(table)
        if strategy is None
        else query_all(table, Key("strategy").eq(strategy))
    )

    return pd.DataFrame(items)


if __name__ == "__main__":
    trades = load_trades()
    print(trades)
