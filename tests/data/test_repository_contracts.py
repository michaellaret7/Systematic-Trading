"""Typed domain records crossing the DynamoDB repository boundary."""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from systematic_trading.data.repository import ideas, ledger
from systematic_trading.domain.ideas import TradeIdea
from systematic_trading.domain.trades import TradeOrder


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


def trade_order() -> TradeOrder:
    """One valid market entry order for repository tests."""
    return TradeOrder(
        strategy="csf_champions",
        idea_id="2026-07-15T00:00:00+00:00#AAPL#61e26b27",
        symbol="AAPL",
        side="buy",
        target_quantity=40,
        submitted_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
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


def test_record_order_serializes_market_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ledger opens the market-order row with zero fills."""
    table = FakeTable()
    monkeypatch.setattr(ledger, "get_table", lambda name: table)
    monkeypatch.setattr(ledger, "is_paper", lambda: True)

    trade_id = ledger.record_order(trade_order())

    assert trade_id.startswith("2026-07-15T00:00:00+00:00#AAPL#")
    assert table.item is not None
    assert table.item["idea_id"] == "2026-07-15T00:00:00+00:00#AAPL#61e26b27"
    assert table.item["target_quantity"] == 40
    assert table.item["filled_quantity"] == 0
    assert table.item["filled_cost"] == Decimal("0")
    assert table.item["filled_price"] is None
    assert table.item["filled_at"] is None
    assert "limit_price" not in table.item
    assert table.item["paper"] is True


def test_complete_order_closes_row_at_broker_average(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fully-filled hook writes absolute quantity, price, cost, and time."""
    table = FakeTable(
        item={
            "strategy": "csf_champions",
            "trade_id": "2026-07-15T00:00:00+00:00#AAPL#aaaa1111",
            "idea_id": "2026-07-15T00:00:00+00:00#AAPL#61e26b27",
            "target_quantity": Decimal("40"),
            "filled_quantity": Decimal("0"),
            "filled_cost": Decimal("0"),
        }
    )
    monkeypatch.setattr(ledger, "get_table", lambda name: table)

    completed_idea = ledger.complete_order(
        "csf_champions",
        "2026-07-15T00:00:00+00:00#AAPL#aaaa1111",
        average_fill_price=10.125,
        filled_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )

    assert completed_idea == "2026-07-15T00:00:00+00:00#AAPL#61e26b27"
    assert table.update_kwargs is not None
    values = table.update_kwargs["ExpressionAttributeValues"]
    assert values[":q"] == 40
    assert values[":c"] == Decimal("405.000")
    assert values[":p"] == Decimal("10.125")
    assert values[":t"] == "2026-07-16T00:00:00+00:00"


def test_complete_order_rejects_unknown_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fill for a row that does not exist fails fast instead of writing."""
    monkeypatch.setattr(ledger, "get_table", lambda name: FakeTable())

    with pytest.raises(KeyError, match="no ledger order"):
        ledger.complete_order(
            "csf_champions",
            "2026-07-15T00:00:00+00:00#AAPL#missing",
            average_fill_price=10.0,
            filled_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )


def test_invalid_domain_records_fail_before_persistence() -> None:
    """Malformed ideas and orders are rejected before repository I/O."""
    with pytest.raises(ValueError, match="score"):
        replace(trade_idea(), score=11.0)

    with pytest.raises(ValueError, match="target_quantity"):
        replace(trade_order(), target_quantity=0)

    with pytest.raises(ValueError, match="idea_id"):
        replace(trade_order(), idea_id="  ")
