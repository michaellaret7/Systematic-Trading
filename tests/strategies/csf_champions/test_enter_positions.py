"""CSF Champions market-entry workflow."""

from datetime import datetime, timezone
from typing import Any

import pytest

from systematic_trading.strategies.csf_champions.portfolio import Holding, Portfolio
from systematic_trading.strategies.csf_champions.workflows import enter_positions as entries


class FakeOrder:
    """One broker order created by the fake strategy."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol


class FakeStrategy:
    """Capture market-order construction and submission without a broker."""

    def __init__(self, last_price: float | None = 100.0) -> None:
        self.is_backtesting = False
        self.portfolio_value = 100_000.0
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
        """Record the submission."""
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


def test_enter_positions_submits_market_order_and_marks_idea_executed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live flow sizes, marks the idea executed, and submits the market order."""
    strategy = FakeStrategy(last_price=100.0)
    status_updates: list[tuple[str, str, str]] = []

    def fake_update_idea_status(strategy_name: str, idea_id: str, status: str) -> None:
        status_updates.append((strategy_name, idea_id, status))
        strategy.idea_is_executed = status == "executed"

    monkeypatch.setattr(entries, "update_idea_status", fake_update_idea_status)

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
    assert status_updates == [("csf_champions", "idea-aapl", "executed")]


def test_enter_positions_skips_invalid_sizing_price(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing broker price cannot produce a meaningful whole-share target."""
    strategy = FakeStrategy(last_price=None)

    entries.enter_positions(strategy, portfolio())

    assert strategy.created == []
    assert strategy.submitted == []
