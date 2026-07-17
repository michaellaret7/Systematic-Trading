"""DynamoDB trade-ideas table: trade proposals from the fundamental agent.

An idea is a proposal, not a trade. The agent submits it as ``pending``; the
executor later marks it ``executed`` (linking the resulting trade-ledger
``trade_id``) or ``rejected``. Each item carries the reference price at
submission time so idea quality can be measured independently of execution.

Keyed like the ledger: ``strategy`` partition + timestamp-prefixed ``idea_id``
sort key, so a query returns ideas in chronological order.
"""

from decimal import Decimal
from uuid import uuid4

import pandas as pd
from boto3.dynamodb.conditions import Attr, Key

from systematic_trading.data.repository.dynamo import get_table, query_all
from systematic_trading.domain.ideas import IDEA_STATUSES, IdeaStatus, TradeIdea

TABLE_NAME = "trade-ideas"


def submit_idea(idea: TradeIdea) -> str:
    """Append one pending trade idea; returns the generated idea_id.

    ``score`` is the agent's 1-10 conviction score, recorded so the book can be
    built by ranking ideas rather than by an absolute cut.
    ``allocation_pct`` is percent-of-portfolio (4.5 means 4.5%);
    ``reference_price`` is the price at submission time, recorded so idea
    quality can later be judged separately from execution quality.
    ``max_entry_price`` is the validity ceiling: the highest entry price at
    which the thesis still clears the return bar — the executor should not
    fill a pending idea above it.
    """
    idea_id = f"{idea.created_at.isoformat()}#{idea.ticker}#{uuid4().hex[:8]}"

    get_table(TABLE_NAME).put_item(
        Item={
            "strategy": idea.strategy,
            "idea_id": idea_id,
            "ticker": idea.ticker,
            "side": idea.side,
            "score": Decimal(str(idea.score)),
            "allocation_pct": Decimal(str(idea.allocation_pct)),
            "thesis": idea.thesis,
            "reference_price": Decimal(str(idea.reference_price)),
            "max_entry_price": Decimal(str(idea.max_entry_price)),
            "created_at": idea.created_at.isoformat(),
            "model": idea.model,
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

    if status not in IDEA_STATUSES:
        raise ValueError(f"unknown status {status!r}; expected one of {IDEA_STATUSES}")

    # 'status' is a DynamoDB reserved word, so the expression aliases it via #s.
    get_table(TABLE_NAME).update_item(
        Key={"strategy": strategy, "idea_id": idea_id},
        UpdateExpression="SET #s = :s, ledger_trade_id = :t",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": status, ":t": ledger_trade_id},
    )


if __name__ == "__main__":
    ideas = load_ideas("csf_champions")

    for idea in ideas.to_dict(orient="records"):
        if idea["allocation_pct"] > 1:
            print(idea["ticker"], idea["allocation_pct"], idea["score"])