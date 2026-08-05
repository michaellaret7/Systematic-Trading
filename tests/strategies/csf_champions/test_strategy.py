"""CSF Champions broker lifecycle hooks."""

import types

from systematic_trading.strategies.csf_champions.portfolio import Portfolio
from systematic_trading.strategies.csf_champions.strategy import CsfChampions


class InitializeContext:
    """Minimal strategy state required by ``initialize``."""

    parameters = {
        "generate_ideas": False,
        "build_portfolio": False,
    }

    def register_cron_callback(self, schedule: str, callback) -> str:
        self.cron_schedule = schedule
        self.cron_callback = callback
        return "job"


class LifecycleContext:
    """Strategy stub for risk lifecycle hooks."""

    def __init__(self) -> None:
        self.portfolio = Portfolio()
        self.pending_sells: list = []
        self.pending_buys: list = []
        self.is_backtesting = False


def test_initialize_sets_intraday_cadence_and_risk_state() -> None:
    """Initialization configures heartbeat, empty order book, and 10:00 cron."""
    context = InitializeContext()
    # Bind lifecycle methods so initialize can register the cron callback.
    context.flush_pending_drawdown_orders = types.MethodType(
        CsfChampions.flush_pending_drawdown_orders,
        context,
    )

    CsfChampions.initialize(context)

    assert context.sleeptime == "2H"
    assert isinstance(context.portfolio, Portfolio)
    assert context.pending_sells == []
    assert context.pending_buys == []
    assert context.cron_schedule == "0 10 * * 1-5"
    assert context.cron_callback == context.flush_pending_drawdown_orders


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


def test_flush_pending_drawdown_orders_submits_the_book(monkeypatch) -> None:
    """10:00 flush hands the book to submit, which drains rows as it sends them."""
    from systematic_trading.strategies.csf_champions import strategy as strategy_module

    context = LifecycleContext()
    context.pending_sells = [("AAPL", 10, "exit")]

    applied: list = []

    def fake_submit(strategy, portfolio, sells, buys) -> bool:
        applied.append((portfolio, list(sells), list(buys)))
        sells.clear()
        buys.clear()
        return True

    monkeypatch.setattr(strategy_module, "submit_drawdown_orders", fake_submit)

    CsfChampions.flush_pending_drawdown_orders(context)

    assert applied == [(context.portfolio, [("AAPL", 10, "exit")], [])]
    assert context.pending_sells == []
    assert context.pending_buys == []


def test_flush_pending_drawdown_orders_keeps_book_when_not_submitted(monkeypatch) -> None:
    """If submit is skipped (e.g. market closed), leave the stash alone."""
    from systematic_trading.strategies.csf_champions import strategy as strategy_module

    context = LifecycleContext()
    context.pending_sells = [("AAPL", 10, "exit")]

    monkeypatch.setattr(
        strategy_module,
        "submit_drawdown_orders",
        lambda *_a, **_k: False,
    )

    CsfChampions.flush_pending_drawdown_orders(context)

    assert context.pending_sells == [("AAPL", 10, "exit")]


def test_flush_pending_drawdown_orders_noop_when_empty(monkeypatch) -> None:
    """No broker work when the book is empty."""
    from systematic_trading.strategies.csf_champions import strategy as strategy_module

    context = LifecycleContext()
    monkeypatch.setattr(
        strategy_module,
        "submit_drawdown_orders",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not submit")),
    )

    CsfChampions.flush_pending_drawdown_orders(context)

    assert context.pending_sells == []
    assert context.pending_buys == []


def test_after_market_closes_appends_sized_rows(monkeypatch) -> None:
    """AMC appends new sells/buys onto any existing pending book."""
    from systematic_trading.strategies.csf_champions import strategy as strategy_module

    context = LifecycleContext()
    context.pending_sells = [("OLD", 2, "exit")]

    monkeypatch.setattr(
        strategy_module,
        "manage_drawdowns",
        lambda strategy, portfolio: ([("MSFT", 5, "trim 50%")], [("AAPL", 1, "add 25%")]),
    )

    CsfChampions.after_market_closes(context)

    assert context.pending_sells == [("OLD", 2, "exit"), ("MSFT", 5, "trim 50%")]
    assert context.pending_buys == [("AAPL", 1, "add 25%")]


def test_after_market_closes_noop_when_nothing_sized(monkeypatch) -> None:
    """Empty lists from manage leave the pending book untouched."""
    from systematic_trading.strategies.csf_champions import strategy as strategy_module

    context = LifecycleContext()
    context.pending_sells = [("OLD", 2, "exit")]

    monkeypatch.setattr(
        strategy_module,
        "manage_drawdowns",
        lambda strategy, portfolio: ([], []),
    )

    CsfChampions.after_market_closes(context)

    assert context.pending_sells == [("OLD", 2, "exit")]
    assert context.pending_buys == []


def test_trading_iteration_flushes_only_in_backtest(monkeypatch) -> None:
    """Crons never register in backtest, so the heartbeat has to flush there."""
    from systematic_trading.strategies.csf_champions import strategy as strategy_module

    flushed: list[str] = []

    monkeypatch.setattr(
        strategy_module,
        "submit_drawdown_orders",
        lambda strategy, portfolio, sells, buys: flushed.append("called") or True,
    )

    live = LifecycleContext()
    live.pending_sells = [("AAPL", 10, "exit")]
    live.flush_pending_drawdown_orders = types.MethodType(
        CsfChampions.flush_pending_drawdown_orders, live
    )

    CsfChampions.on_trading_iteration(live)

    assert flushed == []

    backtest = LifecycleContext()
    backtest.is_backtesting = True
    backtest.pending_sells = [("AAPL", 10, "exit")]
    backtest.flush_pending_drawdown_orders = types.MethodType(
        CsfChampions.flush_pending_drawdown_orders, backtest
    )

    CsfChampions.on_trading_iteration(backtest)

    assert flushed == ["called"]
