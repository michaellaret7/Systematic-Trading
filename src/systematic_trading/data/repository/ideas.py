"""DynamoDB trade-ideas table: trade proposals from the fundamental agent.

An idea is a proposal, not a trade. The agent submits it as ``pending``; the
executor later marks it ``executed`` (linking the resulting trade-ledger
``trade_id``) or ``rejected``. Each item carries the reference price at
submission time so idea quality can be measured independently of execution.

Keyed like the ledger: ``strategy`` partition + timestamp-prefixed ``idea_id``
sort key, so a query returns ideas in chronological order.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import uuid4

import pandas as pd
from boto3.dynamodb.conditions import Attr, Key

from systematic_trading.data.repository.dynamo import get_table, query_all

TABLE_NAME = "trade-ideas"

IdeaSide = Literal["long", "short"]
IdeaStatus = Literal["pending", "executed", "rejected"]

STATUSES: tuple[IdeaStatus, ...] = ("pending", "executed", "rejected")


def submit_idea(
    strategy: str,
    ticker: str,
    side: IdeaSide,
    score: float,
    allocation_pct: float,
    thesis: str,
    reference_price: float,
    model: str,
    created_at: datetime,
) -> str:
    """Append one pending trade idea; returns the generated idea_id.

    ``score`` is the agent's 1-10 conviction score, recorded so the book can be
    built by ranking ideas rather than by an absolute cut.
    ``allocation_pct`` is percent-of-portfolio (4.5 means 4.5%);
    ``reference_price`` is the price at submission time, recorded so idea
    quality can later be judged separately from execution quality.
    """
    idea_id = f"{created_at.isoformat()}#{ticker}#{uuid4().hex[:8]}"

    get_table(TABLE_NAME).put_item(
        Item={
            "strategy": strategy,
            "idea_id": idea_id,
            "ticker": ticker,
            "side": side,
            "score": Decimal(str(score)),
            "allocation_pct": Decimal(str(allocation_pct)),
            "thesis": thesis,
            "reference_price": Decimal(str(reference_price)),
            "created_at": created_at.isoformat(),
            "model": model,
            "status": "pending",
            "ledger_trade_id": None,
        }
    )

    return idea_id


def load_ideas(strategy: str, status: IdeaStatus | None = None) -> pd.DataFrame:
    """Trade ideas for one strategy, oldest first; optionally one status only.

    Returns an empty frame if nothing matches.
    """
    filter_expression = Attr("status").eq(status) if status else None

    items = query_all(get_table(TABLE_NAME), Key("strategy").eq(strategy), filter_expression)

    return pd.DataFrame(items)


def update_idea_status(
    strategy: str,
    idea_id: str,
    status: IdeaStatus,
    ledger_trade_id: str | None = None,
) -> None:
    """Move one idea through its lifecycle; link the ledger fill when executed."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; expected one of {STATUSES}")

    # 'status' is a DynamoDB reserved word, so the expression aliases it via #s.
    get_table(TABLE_NAME).update_item(
        Key={"strategy": strategy, "idea_id": idea_id},
        UpdateExpression="SET #s = :s, ledger_trade_id = :t",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": status, ":t": ledger_trade_id},
    )


if __name__ == "__main__":
    df = load_ideas("trade-ideas")
    print(df.head())