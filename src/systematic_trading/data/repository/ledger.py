"""DynamoDB trade ledger: one item per fill, append-only.

The ledger survives process restarts and box failures because every fill is a
single atomic ``put_item`` — no local state, no file rewrites. Items are keyed
by ``strategy`` (partition) and ``trade_id`` (sort); ``trade_id`` starts with
the ISO fill timestamp so a query returns trades in chronological order.

Strategies record fills from ``on_filled_order`` — live/paper only, never from
backtests (guard with ``self.is_backtesting``).
"""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pandas as pd
from boto3.dynamodb.conditions import Key

from systematic_trading.config import is_paper
from systematic_trading.data.repository.dynamo import get_table, query_all

TABLE_NAME = "trade-ledger"


def record_fill(
    strategy: str,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    filled_at: datetime,
) -> str:
    """Append one fill to the ledger; returns the generated trade_id.

    ``filled_at`` should come from the strategy clock (``self.get_datetime()``).
    The paper/live flag is stamped automatically so paper fills can never be
    mistaken for real-money ones.
    """
    trade_id = f"{filled_at.isoformat()}#{symbol}#{uuid4().hex[:8]}"

    get_table(TABLE_NAME).put_item(
        Item={
            "strategy": strategy,
            "trade_id": trade_id,
            "symbol": symbol,
            "side": side,
            "quantity": Decimal(str(quantity)),
            "price": Decimal(str(price)),
            "filled_at": filled_at.isoformat(),
            "paper": is_paper(),
        }
    )

    return trade_id


def load_trades(strategy: str) -> pd.DataFrame:
    """All recorded fills for one strategy, oldest first.

    Follows DynamoDB pagination so the full history comes back regardless of
    size. Returns an empty frame if the strategy has no trades yet.
    """
    items = query_all(get_table(TABLE_NAME), Key("strategy").eq(strategy))

    return pd.DataFrame(items)


if __name__ == "__main__":
    trades = load_trades("test")
    print(trades)
