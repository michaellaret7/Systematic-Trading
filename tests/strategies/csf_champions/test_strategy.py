"""CSF Champions broker lifecycle hooks."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from systematic_trading.strategies.csf_champions import strategy as strategy_module
from systematic_trading.strategies.csf_champions.strategy import CsfChampions


class FilledHookContext:
    """Minimal strategy state required by ``on_filled_order``."""

    is_backtesting = False
    trade_ids_by_symbol = {"AAPL": "trade-aapl"}

    @staticmethod
    def get_datetime() -> datetime:
        """Return a stable fill timestamp."""
        return datetime(2026, 7, 30, 9, 31, tzinfo=timezone.utc)


class InitializeContext:
    """Minimal strategy state required by ``initialize``."""

    parameters = {
        "generate_ideas": False,
        "build_portfolio": False,
    }


def test_initialize_sets_daily_cadence() -> None:
    """Initialization configures Lumibot to iterate once per trading day."""
    context = InitializeContext()

    CsfChampions.initialize(context)

    assert context.sleeptime == "1D"


def test_filled_hook_completes_ledger_and_idea(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the final fill closes both DynamoDB records at broker average price."""
    completion_calls: list[tuple[str, str, float, datetime]] = []
    idea_updates: list[tuple[str, str, str]] = []

    def fake_complete_order(
        strategy_name: str,
        trade_id: str,
        average_fill_price: float,
        filled_at: datetime,
    ) -> str:
        completion_calls.append((strategy_name, trade_id, average_fill_price, filled_at))
        return "idea-aapl"

    monkeypatch.setattr(strategy_module, "complete_order", fake_complete_order)
    monkeypatch.setattr(
        strategy_module,
        "update_idea_status",
        lambda strategy_name, idea_id, status: idea_updates.append(
            (strategy_name, idea_id, status)
        ),
    )

    order = SimpleNamespace(
        asset=SimpleNamespace(symbol="AAPL"),
        identifier="alpaca-order-aapl",
        avg_fill_price=101.25,
    )

    CsfChampions.on_filled_order(
        FilledHookContext(),
        position=SimpleNamespace(),
        order=order,
        price=102.0,
        quantity=5.0,
        multiplier=1.0,
    )

    assert completion_calls == [
        (
            "csf_champions",
            "trade-aapl",
            101.25,
            datetime(2026, 7, 30, 9, 31, tzinfo=timezone.utc),
        )
    ]
    assert idea_updates == [("csf_champions", "idea-aapl", "filled")]


def test_trading_iteration_logs_daily_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    """The daily iteration remains active without submitting more orders."""
    messages: list[str] = []
    monkeypatch.setattr(strategy_module.log, "info", lambda message: messages.append(message))

    CsfChampions.on_trading_iteration(FilledHookContext())

    assert messages == ["CSF Champions daily trading iteration"]
