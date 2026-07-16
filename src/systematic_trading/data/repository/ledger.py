"""DynamoDB trade ledger: one item per fill, append-only.

The ledger survives process restarts and box failures because every fill is a
single atomic ``put_item`` — no local state, no file rewrites. Items are keyed
by ``strategy`` (partition) and ``trade_id`` (sort); ``trade_id`` starts with
the ISO fill timestamp so a query returns trades in chronological order.

Strategies record fills from ``on_filled_order`` — live/paper only, never from
backtests (guard with ``self.is_backtesting``).
"""

from decimal import Decimal
from uuid import uuid4

import pandas as pd
from boto3.dynamodb.conditions import Key

from systematic_trading.config import is_paper
from systematic_trading.data.repository.dynamo import get_table, query_all
from systematic_trading.domain.trades import TradeFill

TABLE_NAME = "trade-ledger"


def record_fill(fill: TradeFill) -> str:
    """Append one fill to the ledger; returns the generated trade_id.

    ``filled_at`` should come from the strategy clock (``self.get_datetime()``).
    The paper/live flag is stamped automatically so paper fills can never be
    mistaken for real-money ones.
    """
    trade_id = f"{fill.filled_at.isoformat()}#{fill.symbol}#{uuid4().hex[:8]}"

    get_table(TABLE_NAME).put_item(
        Item={
            "strategy": fill.strategy,
            "trade_id": trade_id,
            "symbol": fill.symbol,
            "side": fill.side,
            "quantity": Decimal(str(fill.quantity)),
            "price": Decimal(str(fill.price)),
            "filled_at": fill.filled_at.isoformat(),
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
