"""Typed domain records crossing the DynamoDB repository boundary."""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from systematic_trading.data.repository import ideas
from systematic_trading.domain.ideas import TradeIdea


class FakeTable:
    """Capture DynamoDB reads and writes without network access."""

    def __init__(self, item: dict[str, Any] | None = None) -> None:
        self.item = item
        self.update_kwargs: dict[str, Any] | None = None

    def put_item(self, Item: dict[str, Any]) -> None:  # noqa: N803 - boto3 API shape
        """Capture the item passed to DynamoDB."""
        self.item = Item

    def get_item(  # noqa: N803 - boto3 API shape
        self,
        Key: dict[str, Any],
        ConsistentRead: bool = False,
    ) -> dict[str, Any]:
        """Return the stored item the way DynamoDB wraps it."""
        assert ConsistentRead is True
        return {"Item": self.item} if self.item is not None else {}

    def update_item(self, **kwargs: Any) -> None:
        """Capture the update expression and values passed to DynamoDB."""
        self.update_kwargs = kwargs


def trade_idea() -> TradeIdea:
    """One valid idea for repository tests."""
    return TradeIdea(
        strategy="csf_champions",
        ticker="AAPL",
        side="long",
        score=8.5,
        allocation_pct=2.5,
        thesis="Durable returns on capital.",
        reference_price=200.0,
        model="test-model",
        created_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )


def test_submit_idea_serializes_domain_record(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ideas repository owns DynamoDB-specific serialization."""
    table = FakeTable()
    monkeypatch.setattr(ideas, "get_table", lambda name: table)

    idea_id = ideas.submit_idea(trade_idea())

    assert idea_id.startswith("2026-07-15T00:00:00+00:00#AAPL#")
    assert table.item is not None
    assert table.item["score"] == Decimal("8.5")
    assert table.item["status"] == "pending"


def test_invalid_domain_records_fail_before_persistence() -> None:
    """Malformed ideas are rejected before repository I/O."""
    with pytest.raises(ValueError, match="score"):
        replace(trade_idea(), score=11.0)
