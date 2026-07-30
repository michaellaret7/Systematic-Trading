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
    trade_ids_by_order_id = {"alpaca-order-aapl": "trade-aapl"}

    @staticmethod
    def get_datetime() -> datetime:
        """Return a stable fill timestamp."""
        return datetime(2026, 7, 30, 9, 31, tzinfo=timezone.utc)


class IterationContext:
    """Minimal strategy state required by ``on_trading_iteration``."""

    is_backtesting = False


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
    assert context.trade_ids_by_symbol == {}
    assert context.trade_ids_by_order_id == {}


def test_filled_hook_finalizes_ledger_and_portfolio(monkeypatch: pytest.MonkeyPatch) -> None:
    """Final fill closes ledger + idea and upserts the open portfolio row."""
    finalize_calls: list[dict] = []

    def fake_finalize(strategy_name, trade_id, **kwargs) -> str:
        finalize_calls.append({"strategy": strategy_name, "trade_id": trade_id, **kwargs})
        return "idea-aapl"

    monkeypatch.setattr(strategy_module, "finalize_filled_trade", fake_finalize)

    order = SimpleNamespace(
        asset=SimpleNamespace(symbol="AAPL"),
        identifier="alpaca-order-aapl",
        avg_fill_price=101.25,
    )
    broker_position = SimpleNamespace(quantity=40, side="long", avg_fill_price=101.25)

    CsfChampions.on_filled_order(
        FilledHookContext(),
        position=broker_position,
        order=order,
        price=102.0,
        quantity=40.0,
        multiplier=1.0,
    )

    assert finalize_calls == [
        {
            "strategy": "csf_champions",
            "trade_id": "trade-aapl",
            "symbol": "AAPL",
            "average_fill_price": 101.25,
            "filled_at": datetime(2026, 7, 30, 9, 31, tzinfo=timezone.utc),
            "broker_position": broker_position,
        }
    ]


def test_filled_hook_skips_portfolio_in_backtest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backtests never write ledger, ideas, or portfolio state."""
    called: list[str] = []

    monkeypatch.setattr(
        strategy_module,
        "finalize_filled_trade",
        lambda *a, **k: called.append("finalize"),
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


def test_trading_iteration_reconciles_then_syncs_marks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Daily iteration reconciles missed fills before refreshing marks."""
    calls: list[str] = []

    monkeypatch.setattr(strategy_module.log, "info", lambda *a, **k: None)
    monkeypatch.setattr(
        strategy_module,
        "reconcile_open_orders",
        lambda strategy, strategy_name: calls.append(f"reconcile:{strategy_name}"),
    )
    monkeypatch.setattr(
        strategy_module,
        "sync_position_pnl",
        lambda strategy, strategy_name: calls.append(f"pnl:{strategy_name}"),
    )

    CsfChampions.on_trading_iteration(IterationContext())

    assert calls == ["reconcile:csf_champions", "pnl:csf_champions"]


def test_trading_iteration_skips_live_side_effects_in_backtest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backtests do not reconcile ledger rows or stamp marks."""
    called: list[str] = []

    monkeypatch.setattr(strategy_module.log, "info", lambda *a, **k: None)
    monkeypatch.setattr(
        strategy_module,
        "reconcile_open_orders",
        lambda *a, **k: called.append("reconcile"),
    )
    monkeypatch.setattr(
        strategy_module,
        "sync_position_pnl",
        lambda *a, **k: called.append("pnl"),
    )

    context = IterationContext()
    context.is_backtesting = True
    CsfChampions.on_trading_iteration(context)

    assert called == []
