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


class IterationContext:
    """Minimal strategy state required by ``on_trading_iteration``."""

    is_backtesting = False

    def __init__(self, api: object | None = None) -> None:
        self.broker = SimpleNamespace(api=api)

    @staticmethod
    def get_datetime() -> datetime:
        """Return a stable mark timestamp."""
        return datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc)


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


def test_filled_hook_completes_ledger_idea_and_portfolio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Final fill closes ledger + idea and delegates portfolio book sync."""
    completion_calls: list[tuple[str, str, float, datetime]] = []
    idea_updates: list[tuple[str, str, str]] = []
    portfolio_calls: list[dict] = []

    def fake_complete_order(
        strategy_name: str,
        trade_id: str,
        average_fill_price: float,
        filled_at: datetime,
    ) -> str:
        completion_calls.append((strategy_name, trade_id, average_fill_price, filled_at))
        return "idea-aapl"

    def fake_sync_portfolio_from_fill(strategy_name: str, broker_position, **kwargs) -> None:
        portfolio_calls.append(
            {
                "strategy": strategy_name,
                "broker_position": broker_position,
                **kwargs,
            }
        )

    monkeypatch.setattr(strategy_module, "complete_order", fake_complete_order)
    monkeypatch.setattr(
        strategy_module,
        "update_idea_status",
        lambda strategy_name, idea_id, status: idea_updates.append(
            (strategy_name, idea_id, status)
        ),
    )
    monkeypatch.setattr(
        strategy_module,
        "sync_portfolio_from_fill",
        fake_sync_portfolio_from_fill,
    )

    order = SimpleNamespace(
        asset=SimpleNamespace(symbol="AAPL"),
        identifier="alpaca-order-aapl",
        avg_fill_price=101.25,
    )
    broker_position = SimpleNamespace(
        quantity=40,
        side="long",
        avg_fill_price=101.25,
    )

    CsfChampions.on_filled_order(
        FilledHookContext(),
        position=broker_position,
        order=order,
        price=102.0,
        quantity=40.0,
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
    assert portfolio_calls == [
        {
            "strategy": "csf_champions",
            "broker_position": broker_position,
            "symbol": "AAPL",
            "idea_id": "idea-aapl",
            "filled_at": datetime(2026, 7, 30, 9, 31, tzinfo=timezone.utc),
        }
    ]


def test_filled_hook_skips_portfolio_in_backtest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backtests never write ledger, ideas, or portfolio state."""
    called: list[str] = []

    monkeypatch.setattr(
        strategy_module,
        "complete_order",
        lambda *a, **k: called.append("complete") or "idea",
    )
    monkeypatch.setattr(
        strategy_module,
        "update_idea_status",
        lambda *a, **k: called.append("idea"),
    )
    monkeypatch.setattr(
        strategy_module,
        "sync_portfolio_from_fill",
        lambda *a, **k: called.append("portfolio"),
    )

    context = FilledHookContext()
    context.is_backtesting = True
    order = SimpleNamespace(
        asset=SimpleNamespace(symbol="AAPL"),
        identifier="id",
        avg_fill_price=100.0,
    )

    CsfChampions.on_filled_order(
        context,
        position=SimpleNamespace(quantity=1, side="long", avg_fill_price=100.0),
        order=order,
        price=100.0,
        quantity=1.0,
        multiplier=1.0,
    )

    assert called == []


def test_trading_iteration_calls_shared_mark_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """Daily iteration delegates mark refresh to the shared portfolio helper."""
    calls: list[tuple[object, str]] = []

    monkeypatch.setattr(strategy_module.log, "info", lambda *a, **k: None)
    monkeypatch.setattr(
        strategy_module,
        "sync_position_marks",
        lambda strategy, strategy_name: calls.append((strategy, strategy_name)),
    )

    context = IterationContext()
    CsfChampions.on_trading_iteration(context)

    assert calls == [(context, "csf_champions")]


def test_trading_iteration_skips_marks_in_backtest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backtests do not touch the portfolio mark columns."""
    called: list[str] = []

    monkeypatch.setattr(strategy_module.log, "info", lambda *a, **k: None)
    monkeypatch.setattr(
        strategy_module,
        "sync_position_marks",
        lambda *a, **k: called.append("marks"),
    )

    context = IterationContext()
    context.is_backtesting = True

    CsfChampions.on_trading_iteration(context)

    assert called == []


def test_trading_iteration_logs_daily_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    """The daily iteration remains active without submitting more orders."""
    messages: list[str] = []
    monkeypatch.setattr(strategy_module.log, "info", lambda message, *a: messages.append(message))
    monkeypatch.setattr(strategy_module, "sync_position_marks", lambda *a, **k: None)

    CsfChampions.on_trading_iteration(IterationContext())

    assert messages[0] == "CSF Champions daily trading iteration"
