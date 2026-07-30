"""Typed domain records crossing the DynamoDB repository boundary."""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from systematic_trading.data.repository import ideas, ledger, portfolio
from systematic_trading.domain.ideas import TradeIdea
from systematic_trading.domain.portfolio import Position, PositionMarks
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
        symbol="AAPL",
        side="buy",
        target_quantity=40,
        submitted_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        idea_id="2026-07-15T00:00:00+00:00#AAPL#61e26b27",
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
    assert table.item["target_quantity"] == Decimal("40")
    assert table.item["filled_quantity"] == Decimal("0")
    assert table.item["filled_cost"] == Decimal("0")
    assert table.item["filled_price"] is None
    assert table.item["filled_at"] is None
    assert "limit_price" not in table.item
    assert table.item["paper"] is True


def test_record_order_omits_idea_id_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Orders without a trade-ideas link do not write idea_id."""
    table = FakeTable()
    monkeypatch.setattr(ledger, "get_table", lambda name: table)
    monkeypatch.setattr(ledger, "is_paper", lambda: True)

    ledger.record_order(
        TradeOrder(
            strategy="btc_ticker",
            symbol="BTC",
            side="buy",
            target_quantity=0.0002,
            submitted_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )
    )

    assert table.item is not None
    assert "idea_id" not in table.item


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
    assert values[":q"] == Decimal("40")
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


def test_complete_order_is_idempotent_when_already_filled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second complete for the same row does not rewrite fill fields."""
    table = FakeTable(
        item={
            "strategy": "csf_champions",
            "trade_id": "trade-1",
            "idea_id": "idea-1",
            "target_quantity": Decimal("10"),
            "filled_at": "2026-07-16T00:00:00+00:00",
        }
    )
    monkeypatch.setattr(ledger, "get_table", lambda name: table)

    idea_id = ledger.complete_order(
        "csf_champions",
        "trade-1",
        average_fill_price=12.0,
        filled_at=datetime(2026, 7, 17, tzinfo=timezone.utc),
    )

    assert idea_id == "idea-1"
    assert table.update_kwargs is None


def test_attach_broker_order_id_persists_broker_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Broker order ids are stored for durable reconcile after restart."""
    table = FakeTable()
    monkeypatch.setattr(ledger, "get_table", lambda name: table)

    ledger.attach_broker_order_id("csf_champions", "trade-1", "alpaca-oid")

    assert table.update_kwargs is not None
    assert table.update_kwargs["Key"] == {"strategy": "csf_champions", "trade_id": "trade-1"}
    assert table.update_kwargs["ExpressionAttributeValues"][":b"] == "alpaca-oid"


def test_load_open_orders_filters_completed_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only rows without filled_at are open."""
    monkeypatch.setattr(
        ledger,
        "query_all",
        lambda table, key: [
            {"trade_id": "open", "filled_at": None},
            {"trade_id": "done", "filled_at": "2026-07-16T00:00:00+00:00"},
            {"trade_id": "also-open"},
        ],
    )
    monkeypatch.setattr(ledger, "get_table", lambda name: FakeTable())

    open_rows = ledger.load_open_orders("csf_champions")

    assert [row["trade_id"] for row in open_rows] == ["open", "also-open"]


def test_invalid_domain_records_fail_before_persistence() -> None:
    """Malformed ideas and orders are rejected before repository I/O."""
    with pytest.raises(ValueError, match="score"):
        replace(trade_idea(), score=11.0)

    with pytest.raises(ValueError, match="target_quantity"):
        replace(trade_order(), target_quantity=0)

    with pytest.raises(ValueError, match="idea_id"):
        replace(trade_order(), idea_id="  ")

    # No idea is valid for sleeves that do not use the trade-ideas table.
    TradeOrder(
        strategy="btc_ticker",
        symbol="BTC",
        side="buy",
        target_quantity=0.0002,
        submitted_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    with pytest.raises(ValueError, match="quantity"):
        replace(open_position(), quantity=0)


def open_position() -> Position:
    """One valid open portfolio position."""
    return Position(
        strategy="csf_champions",
        symbol="AAPL",
        side="long",
        quantity=40,
        avg_cost=101.25,
        opened_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        idea_id="2026-07-15T00:00:00+00:00#AAPL#61e26b27",
    )


def position_marks() -> PositionMarks:
    """One valid Alpaca mark snapshot."""
    return PositionMarks(
        strategy="csf_champions",
        symbol="AAPL",
        unrealized_pl=12.5,
        unrealized_plpc=0.025,
        current_price=205.0,
        market_value=8200.0,
        mark_synced_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )


def test_apply_broker_position_upserts_book_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fill path writes book fields via update_item so marks are preserved."""
    table = FakeTable()
    monkeypatch.setattr(portfolio, "get_table", lambda name: table)
    monkeypatch.setattr(portfolio, "is_paper", lambda: True)

    portfolio.apply_broker_position(
        "csf_champions",
        "AAPL",
        quantity=40,
        side="long",
        avg_cost=101.25,
        now=datetime(2026, 7, 15, tzinfo=timezone.utc),
        idea_id="idea-aapl",
    )

    assert table.update_kwargs is not None
    assert table.update_kwargs["Key"] == {"strategy": "csf_champions", "symbol": "AAPL"}
    values = table.update_kwargs["ExpressionAttributeValues"]
    assert values[":q"] == Decimal("40")
    assert values[":c"] == Decimal("101.25")
    assert values[":p"] is True
    assert values[":idea"] == "idea-aapl"
    assert "if_not_exists(opened_at" in table.update_kwargs["UpdateExpression"]


def test_apply_broker_position_deletes_when_flat(monkeypatch: pytest.MonkeyPatch) -> None:
    """A flat broker position removes the portfolio row."""
    deleted: list[dict[str, str]] = []

    class DeleteTable(FakeTable):
        def delete_item(self, Key: dict[str, str]) -> None:  # noqa: N803
            deleted.append(Key)

    monkeypatch.setattr(portfolio, "get_table", lambda name: DeleteTable())

    portfolio.apply_broker_position(
        "csf_champions",
        "AAPL",
        quantity=0,
        side="long",
        avg_cost=101.25,
        now=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert deleted == [{"strategy": "csf_champions", "symbol": "AAPL"}]


def test_update_marks_serializes_alpaca_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mark sync writes only observational columns."""
    table = FakeTable()
    monkeypatch.setattr(portfolio, "get_table", lambda name: table)

    portfolio.update_marks(position_marks())

    assert table.update_kwargs is not None
    values = table.update_kwargs["ExpressionAttributeValues"]
    assert values[":pl"] == Decimal("12.5")
    assert values[":plpc"] == Decimal("0.025")
    assert values[":px"] == Decimal("205.0")
    assert values[":mv"] == Decimal("8200.0")
    assert values[":t"] == "2026-07-16T00:00:00+00:00"


def test_seed_position_writes_book_and_marks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bootstrap put includes book fields and the first mark snapshot."""
    table = FakeTable()
    monkeypatch.setattr(portfolio, "get_table", lambda name: table)
    monkeypatch.setattr(portfolio, "is_paper", lambda: True)

    portfolio.seed_position(open_position(), position_marks())

    assert table.item is not None
    assert table.item["quantity"] == Decimal("40")
    assert table.item["avg_cost"] == Decimal("101.25")
    assert table.item["unrealized_plpc"] == Decimal("0.025")
    assert table.item["paper"] is True
