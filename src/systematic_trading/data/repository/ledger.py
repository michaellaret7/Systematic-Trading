"""DynamoDB trade ledger: one item per market entry order.

Each item is created before broker submission with the full ``target_quantity``
and zero fills. A broker completion event (or reconcile pass) closes the item
with the order's full quantity, average fill price, total cost, and fill
timestamp. ``broker_order_id`` is attached after submission so restarts can
reconcile fills without the in-memory map.

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


def _idea_id_from_item(item: dict) -> str | None:
    """Return the linked idea_id when present."""
    idea_id = item.get("idea_id")

    return str(idea_id) if idea_id is not None else None


def record_order(order: TradeOrder) -> str:
    """Create one market entry in the ledger; return its trade ID.

    ``submitted_at`` should come from the strategy clock
    (``self.get_datetime()``). The row is created before broker submission so
    a fast market fill can always find it. The paper/live flag is stamped
    automatically so paper orders can never be mistaken for real-money ones.
    ``idea_id`` is stored only when the order is linked to a trade-ideas row.
    """
    trade_id = f"{order.submitted_at.isoformat()}#{order.symbol}#{uuid4().hex[:8]}"

    item: dict = {
        "strategy": order.strategy,
        "trade_id": trade_id,
        "symbol": order.symbol,
        "side": order.side,
        "target_quantity": Decimal(str(order.target_quantity)),
        "filled_quantity": Decimal("0"),
        "filled_cost": Decimal("0"),
        "filled_price": None,
        "filled_at": None,
        "submitted_at": order.submitted_at.isoformat(),
        "paper": is_paper(),
    }

    if order.idea_id is not None:
        item["idea_id"] = order.idea_id

    get_table(TABLE_NAME).put_item(Item=item)

    return trade_id


def attach_broker_order_id(strategy: str, trade_id: str, broker_order_id: str) -> None:
    """Persist the broker's order id so reconcile can close the row after restart."""
    if not broker_order_id.strip():
        raise ValueError("broker_order_id must not be empty")

    get_table(TABLE_NAME).update_item(
        Key={"strategy": strategy, "trade_id": trade_id},
        UpdateExpression="SET broker_order_id = :b",
        ExpressionAttributeValues={":b": broker_order_id},
    )


def complete_order(
    strategy: str,
    trade_id: str,
    average_fill_price: float,
    filled_at: datetime,
) -> str | None:
    """Close one ledger row from a fully-filled broker order.

    Idempotent: if ``filled_at`` is already set, returns the stored idea_id
    without rewriting. Returns the linked ``idea_id`` when present.
    """
    if not isfinite(average_fill_price) or average_fill_price <= 0:
        raise ValueError("average_fill_price must be positive")

    table = get_table(TABLE_NAME)
    item = _load_order(table, strategy, trade_id)

    if item.get("filled_at"):
        return _idea_id_from_item(item)

    filled_quantity = Decimal(str(item["target_quantity"]))
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

    return _idea_id_from_item(item)


def load_open_orders(strategy: str) -> list[dict]:
    """Ledger rows for one strategy that are not yet fully filled."""
    items = query_all(get_table(TABLE_NAME), Key("strategy").eq(strategy))

    return [item for item in items if not item.get("filled_at")]


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
