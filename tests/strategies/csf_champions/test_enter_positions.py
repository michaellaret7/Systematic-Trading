"""CSF Champions market-entry workflow."""

from datetime import datetime, timezone
from typing import Any

import pytest

from systematic_trading.domain.trades import TradeOrder
from systematic_trading.strategies.csf_champions.portfolio import Holding, Portfolio
from systematic_trading.strategies.csf_champions.workflows import enter_positions as entries


class FakeOrder:
    """One broker order created by the fake strategy."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.identifier = f"broker-{symbol}"


class FakeStrategy:
    """Capture market-order construction and submission without a broker."""

    def __init__(self, last_price: float | None = 100.0) -> None:
        self.is_backtesting = False
        self.portfolio_value = 100_000.0
        self.trade_ids_by_symbol: dict[str, str] = {}
        self.trade_ids_by_order_id: dict[str, str] = {}
        self.last_price = last_price
        self.created: list[dict[str, Any]] = []
        self.submitted: list[FakeOrder] = []
        self.idea_is_executed = False

    def get_last_price(self, symbol: str) -> float | None:
        """Return the configured sizing price."""
        return self.last_price

    def create_order(
        self,
        symbol: str,
        quantity: int,
        side: str,
        **kwargs: Any,
    ) -> FakeOrder:
        """Capture the order request."""
        self.created.append(
            {
                "symbol": symbol,
                "quantity": quantity,
                "side": side,
                **kwargs,
            }
        )

        return FakeOrder(symbol)

    def submit_order(self, order: FakeOrder) -> None:
        """Verify the ledger mapping exists before the fast market submission."""
        assert order.symbol in self.trade_ids_by_symbol
        assert self.idea_is_executed
        self.submitted.append(order)

    def get_datetime(self) -> datetime:
        """Return a stable strategy timestamp."""
        return datetime(2026, 7, 30, 9, 30, tzinfo=timezone.utc)


def portfolio() -> Portfolio:
    """One long holding ready for market entry."""
    result = Portfolio()
    result.add(
        Holding(
            idea_id="idea-aapl",
            ticker="AAPL",
            sector="Technology",
            industry="Hardware",
            side="long",
            score=8.5,
            weight_pct=2.0,
            thesis="Durable returns.",
            reference_price=99.0,
        )
    )

    return result


def test_enter_positions_submits_market_order_after_registering_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The simple live flow sizes, records, maps, submits, and marks executed."""
    strategy = FakeStrategy(last_price=100.0)
    recorded: list[TradeOrder] = []
    status_updates: list[tuple[str, str, str]] = []
    attached: list[tuple[str, str, str]] = []

    def fake_record_order(order: TradeOrder) -> str:
        recorded.append(order)
        return "trade-aapl"

    def fake_update_idea_status(strategy_name: str, idea_id: str, status: str) -> None:
        status_updates.append((strategy_name, idea_id, status))
        strategy.idea_is_executed = status == "executed"

    def fake_attach(strategy_name: str, trade_id: str, broker_order_id: str) -> None:
        attached.append((strategy_name, trade_id, broker_order_id))

    monkeypatch.setattr(entries, "record_order", fake_record_order)
    monkeypatch.setattr(entries, "update_idea_status", fake_update_idea_status)
    monkeypatch.setattr(entries, "attach_broker_order_id", fake_attach)

    entries.enter_positions(strategy, portfolio())

    assert strategy.created == [
        {
            "symbol": "AAPL",
            "quantity": 20,
            "side": "buy",
            "order_type": "market",
            "time_in_force": "day",
        }
    ]
    assert len(strategy.submitted) == 1
    assert strategy.trade_ids_by_symbol == {"AAPL": "trade-aapl"}
    assert strategy.trade_ids_by_order_id == {"broker-AAPL": "trade-aapl"}
    assert attached == [("csf_champions", "trade-aapl", "broker-AAPL")]
    assert recorded[0].target_quantity == 20
    assert status_updates == [("csf_champions", "idea-aapl", "executed")]


def test_enter_positions_skips_invalid_sizing_price(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing broker price cannot produce a meaningful whole-share target."""
    strategy = FakeStrategy(last_price=None)
    monkeypatch.setattr(
        entries,
        "record_order",
        lambda order: pytest.fail("invalid entry must not reach the ledger"),
    )

    entries.enter_positions(strategy, portfolio())

    assert strategy.created == []
    assert strategy.submitted == []
