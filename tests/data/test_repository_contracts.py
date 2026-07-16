"""Typed domain records crossing the DynamoDB repository boundary."""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from systematic_trading.data.repository import ideas, ledger
from systematic_trading.domain.ideas import TradeIdea
from systematic_trading.domain.trades import TradeFill


class FakeTable:
    """Capture DynamoDB writes without network access."""

    def __init__(self) -> None:
        self.item: dict[str, Any] | None = None

    def put_item(self, Item: dict[str, Any]) -> None:  # noqa: N803 - boto3 API shape
        """Capture the item passed to DynamoDB."""
        self.item = Item


def trade_idea() -> TradeIdea:
    """One valid idea for repository tests."""
    return TradeIdea(
        strategy="csf_champions",
        ticker="AAPL",
        side="long",
        score=8.5,
        allocation_pct=4.0,
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


def test_record_fill_serializes_domain_record(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ledger repository stamps mode and serializes numeric values."""
    table = FakeTable()
    monkeypatch.setattr(ledger, "get_table", lambda name: table)
    monkeypatch.setattr(ledger, "is_paper", lambda: True)
    fill = TradeFill(
        strategy="csf_champions",
        symbol="AAPL",
        side="buy",
        quantity=2.0,
        price=200.0,
        filled_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    trade_id = ledger.record_fill(fill)

    assert trade_id.startswith("2026-07-15T00:00:00+00:00#AAPL#")
    assert table.item is not None
    assert table.item["quantity"] == Decimal("2.0")
    assert table.item["paper"] is True


def test_invalid_domain_records_fail_before_persistence() -> None:
    """Malformed ideas and fills are rejected before repository I/O."""
    with pytest.raises(ValueError, match="score"):
        replace(trade_idea(), score=11.0)

    with pytest.raises(ValueError, match="quantity"):
        TradeFill(
            strategy="csf_champions",
            symbol="AAPL",
            side="buy",
            quantity=0.0,
            price=200.0,
            filled_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )
