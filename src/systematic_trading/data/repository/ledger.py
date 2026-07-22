"""DynamoDB trade ledger: one item per entry order, updated as fills arrive.

Each item is created at order submission with the full ``target_quantity`` and
zero fills; broker fill events then accumulate ``filled_quantity`` and
``filled_cost`` (total dollars, so the average price stays exact across
partial fills on different days). When the target is reached the item is
closed out with ``filled_price`` (the weighted average) and ``filled_at``.

Items are keyed by ``strategy`` (partition) and ``trade_id`` (sort);
``trade_id`` starts with the ISO submission timestamp so a query returns
orders in chronological order.

Strategies write from live/paper runs only, never from backtests (guard with
``self.is_backtesting``).
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pandas as pd
from boto3.dynamodb.conditions import Attr, Key

from systematic_trading.config import is_paper
from systematic_trading.data.repository.dynamo import get_table, query_all
from systematic_trading.domain.trades import TradeOrder

TABLE_NAME = "trade-ledger"


#     ================================
# --> Helper funcs
#     ================================


def _load_order(table: Any, strategy: str, trade_id: str) -> dict:
    """Fetch one ledger item, failing fast if the row does not exist."""
    item = table.get_item(Key={"strategy": strategy, "trade_id": trade_id}).get("Item")

    if item is None:
        raise KeyError(f"no ledger order {trade_id!r} for strategy {strategy!r}")

    return item


def _write_fill_state(
    table: Any,
    strategy: str,
    trade_id: str,
    item: dict,
    filled_quantity: int,
    filled_cost: Decimal,
    completion_price: Decimal,
    filled_at: datetime,
) -> str | None:
    """Persist fill state; close the row and return its idea_id at target.

    ``completion_price`` and ``filled_at`` are only written when
    ``filled_quantity`` reaches the row's target.
    """
    updates: dict = {
        ":q": filled_quantity,
        ":c": filled_cost,
    }
    expression = "SET filled_quantity = :q, filled_cost = :c"
    completed = filled_quantity >= int(item["target_quantity"])

    if completed:
        expression += ", filled_price = :p, filled_at = :t"
        updates[":p"] = completion_price
        updates[":t"] = filled_at.isoformat()

    table.update_item(
        Key={"strategy": strategy, "trade_id": trade_id},
        UpdateExpression=expression,
        ExpressionAttributeValues=updates,
    )

    return str(item["idea_id"]) if completed else None


def record_order(order: TradeOrder) -> str:
    """Append one submitted entry order to the ledger; returns the trade_id.

    ``submitted_at`` should come from the strategy clock
    (``self.get_datetime()``). The paper/live flag is stamped automatically so
    paper orders can never be mistaken for real-money ones.
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
            "limit_price": Decimal(str(order.limit_price)),
            "submitted_at": order.submitted_at.isoformat(),
            "paper": is_paper(),
        }
    )

    return trade_id


def apply_fill(
    strategy: str,
    trade_id: str,
    quantity: int,
    price: float,
    filled_at: datetime,
) -> str | None:
    """Fold one broker fill into its ledger order.

    Accumulates ``filled_quantity`` and ``filled_cost``; once the target
    quantity is reached, stamps ``filled_price`` (weighted average) and
    ``filled_at``. ``filled_at`` should come from the strategy clock and is
    only written when this fill completes the order.

    Returns the order's ``idea_id`` when this fill completes it (so the caller
    can move the idea to ``filled``), otherwise ``None``.
    """
    table = get_table(TABLE_NAME)
    item = _load_order(table, strategy, trade_id)

    filled_quantity = int(item["filled_quantity"]) + quantity
    filled_cost = item["filled_cost"] + Decimal(str(price)) * quantity

    return _write_fill_state(
        table,
        strategy,
        trade_id,
        item,
        filled_quantity,
        filled_cost,
        completion_price=filled_cost / filled_quantity,
        filled_at=filled_at,
    )


def sync_fill(
    strategy: str,
    trade_id: str,
    filled_quantity: int,
    avg_price: float,
    filled_at: datetime,
) -> str | None:
    """Overwrite one order's fill state with broker truth.

    The daily sweep uses this to heal fills the event hooks missed (Lumibot
    silently drops trade events during a session's first iteration). Unlike
    ``apply_fill`` this sets absolute values — quantity from the broker
    position, cost from its average entry price — so it is idempotent.

    Returns the order's ``idea_id`` when the synced quantity completes it,
    otherwise ``None``.
    """
    table = get_table(TABLE_NAME)
    item = _load_order(table, strategy, trade_id)

    avg = Decimal(str(avg_price))

    return _write_fill_state(
        table,
        strategy,
        trade_id,
        item,
        filled_quantity,
        filled_cost=avg * filled_quantity,
        completion_price=avg,
        filled_at=filled_at,
    )


def load_open_orders(strategy: str) -> pd.DataFrame:
    """Orders not yet fully filled for one strategy, oldest first.

    An order is open while ``filled_at`` is still null. Returns an empty frame
    if everything is filled.
    """
    items = query_all(
        get_table(TABLE_NAME),
        Key("strategy").eq(strategy),
        Attr("filled_at").eq(None),
    )

    return pd.DataFrame(items)


def load_trades(strategy: str) -> pd.DataFrame:
    """All recorded orders for one strategy, oldest first.

    Follows DynamoDB pagination so the full history comes back regardless of
    size. Returns an empty frame if the strategy has no orders yet.
    """
    items = query_all(get_table(TABLE_NAME), Key("strategy").eq(strategy))

    return pd.DataFrame(items)


if __name__ == "__main__":
    trades = load_trades("csf_champions")
    print(trades)
