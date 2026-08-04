"""CSF Champions broker lifecycle hooks."""

from systematic_trading.strategies.csf_champions.agents.risk_manager.models import (
    DrawdownDecision,
)
from systematic_trading.strategies.csf_champions.portfolio import Portfolio
from systematic_trading.strategies.csf_champions.strategy import CsfChampions


class InitializeContext:
    """Minimal strategy state required by ``initialize``."""

    parameters = {
        "generate_ideas": False,
        "build_portfolio": False,
    }


class LifecycleContext:
    """Strategy stub for risk lifecycle hooks."""

    def __init__(self) -> None:
        self.portfolio = Portfolio()
        self.pending_drawdown_orders: list = []


def test_initialize_sets_intraday_cadence_and_risk_state() -> None:
    """Initialization configures heartbeat and empty pending risk queue."""
    context = InitializeContext()

    CsfChampions.initialize(context)

    assert context.sleeptime == "2H"
    assert isinstance(context.portfolio, Portfolio)
    assert context.pending_drawdown_orders == []


def test_before_market_opens_clears_expired_reviews(monkeypatch) -> None:
    """BMO only expires cooldowns."""
    from systematic_trading.strategies.csf_champions import strategy as strategy_module

    context = LifecycleContext()
    called: list[tuple] = []

    monkeypatch.setattr(
        strategy_module,
        "clear_expired_drawdown_reviews",
        lambda strategy, portfolio: called.append((strategy, portfolio)) or ["AAPL"],
    )

    CsfChampions.before_market_opens(context)

    assert called == [(context, context.portfolio)]


def test_on_trading_iteration_applies_and_clears_pending(monkeypatch) -> None:
    """Pending AMC decisions are submitted once, then the queue is emptied."""
    from systematic_trading.strategies.csf_champions import strategy as strategy_module

    context = LifecycleContext()
    decision = DrawdownDecision(ticker="AAPL", action="exit", reason="test", amount=None)
    breach = ("AAPL", -30.0, -30.0, 100.0, None)
    context.pending_drawdown_orders = [(breach, decision)]

    applied: list = []
    monkeypatch.setattr(
        strategy_module,
        "submit_drawdown_orders",
        lambda strategy, orders: applied.append(list(orders)) or ([], []),
    )

    CsfChampions.on_trading_iteration(context)

    assert applied == [[(breach, decision)]]
    assert context.pending_drawdown_orders == []


def test_on_trading_iteration_noop_without_pending(monkeypatch) -> None:
    """No broker work when the queue is empty."""
    from systematic_trading.strategies.csf_champions import strategy as strategy_module

    context = LifecycleContext()
    monkeypatch.setattr(
        strategy_module,
        "submit_drawdown_orders",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not submit")),
    )

    CsfChampions.on_trading_iteration(context)

    assert context.pending_drawdown_orders == []


def test_after_market_closes_queues_actionable_orders(monkeypatch) -> None:
    """AMC runs the review and stashes orders for the next session."""
    from systematic_trading.strategies.csf_champions import strategy as strategy_module

    context = LifecycleContext()
    decision = DrawdownDecision(ticker="MSFT", action="trim", reason="test", amount=0.5)
    breach = ("MSFT", -28.0, -10.0, 200.0, None)
    queued = [(breach, decision)]

    monkeypatch.setattr(
        strategy_module,
        "manage_drawdowns",
        lambda strategy, portfolio: queued,
    )

    CsfChampions.after_market_closes(context)

    assert context.pending_drawdown_orders == queued
