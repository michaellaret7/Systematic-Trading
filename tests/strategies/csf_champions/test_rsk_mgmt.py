"""CSF Champions drawdown risk-management workflow."""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from alpaca.trading.enums import OrderSide

from systematic_trading.strategies.csf_champions.agents.risk_manager.models import (
    DrawdownDecision,
)
from systematic_trading.strategies.csf_champions.portfolio import Portfolio
from systematic_trading.strategies.csf_champions.workflows import rsk_mgmt as risk


#     ================================
# --> Fakes
#     ================================


class FakePosition:
    """Minimal Alpaca-like position for breach checks."""

    def __init__(
        self,
        symbol: str,
        unrealized_plpc: float,
        avg_entry_price: float = 100.0,
        qty: float = 10.0,
        current_price: float | None = None,
    ) -> None:
        self.symbol = symbol
        self.unrealized_plpc = unrealized_plpc
        self.avg_entry_price = avg_entry_price
        self.qty = qty

        # Default to the price implied by the reported PnL so fakes stay consistent.
        sign = -1.0 if qty < 0 else 1.0
        self.current_price = (
            current_price
            if current_price is not None
            else avg_entry_price * (1.0 + sign * unrealized_plpc)
        )


class FakeOrder:
    """Minimal Alpaca-like filled order."""

    def __init__(self, side: Any, filled_qty: float, filled_at: datetime) -> None:
        self.side = side
        self.filled_qty = filled_qty
        self.filled_at = filled_at


class FakeStrategy:
    """Strategy stub with broker positions and a fixed calendar day."""

    def __init__(
        self,
        positions: list[FakePosition] | None = None,
        as_of: date = date(2026, 7, 30),
        orders: dict[str, list[FakeOrder]] | None = None,
    ) -> None:
        self._positions = positions or []
        self._as_of = as_of
        self._orders = orders or {}
        self.broker = SimpleNamespace(
            api=SimpleNamespace(
                get_all_positions=self._get_positions,
                get_orders=self._get_orders,
            )
        )

    def _get_positions(self) -> list[FakePosition]:
        return self._positions

    def _get_orders(self, filter: Any) -> list[FakeOrder]:  # noqa: A002 - matches alpaca-py
        symbol = filter.symbols[0]

        # Default: one opening buy large enough to match any single-entry position.
        return self._orders.get(
            symbol,
            [FakeOrder("buy", 10.0, datetime(2026, 1, 5, tzinfo=timezone.utc))],
        )

    def get_datetime(self) -> datetime:
        return datetime(
            self._as_of.year,
            self._as_of.month,
            self._as_of.day,
            9,
            30,
            tzinfo=timezone.utc,
        )


class FakeAgent:
    """Return a fixed decision, or fail for selected tickers."""

    def __init__(
        self,
        action: str = "hold",
        amount: float | None = None,
        fail_tickers: set[str] | None = None,
        action_by_ticker: dict[str, tuple[str, float | None]] | None = None,
    ) -> None:
        self.action = action
        self.amount = amount
        self.fail_tickers = fail_tickers or set()
        self.action_by_ticker = action_by_ticker or {}
        self.tasks: list[str] = []

    def run(self, task: str, sink: Any) -> DrawdownDecision:
        self.tasks.append(task)
        ticker = task.split("Review drawdown on ", maxsplit=1)[1].split(":", maxsplit=1)[0]

        if ticker in self.fail_tickers:
            raise RuntimeError(f"agent failed for {ticker}")

        if ticker in self.action_by_ticker:
            action, amount = self.action_by_ticker[ticker]
        else:
            action, amount = self.action, self.amount

        return DrawdownDecision(
            ticker=ticker,
            action=action,  # type: ignore[arg-type]
            reason=f"test decision for {ticker}",
            amount=amount,
        )


def _breach(
    ticker: str,
    give_back: float = -30.0,
    pnl_pct: float = -30.0,
    avg_entry: float = 50.0,
    as_of: date = date(2026, 7, 30),
) -> risk.DrawdownBreach:
    return (ticker, give_back, pnl_pct, avg_entry, as_of)


@pytest.fixture(autouse=True)
def flat_price_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """No stored history by default, so the high-water mark comes from entry alone."""
    monkeypatch.setattr(
        risk, "load_daily_prices", lambda **_: pd.DataFrame({"date": [], "close": []})
    )


#     ================================
# --> check_for_drawdown_breaches
#     ================================


def test_check_for_drawdown_breaches_flags_only_under_threshold() -> None:
    """Only positions below the threshold are returned as breaches."""
    strategy = FakeStrategy(
        positions=[
            FakePosition("BAD", unrealized_plpc=-0.30, avg_entry_price=80.0),
            FakePosition("OK", unrealized_plpc=-0.10, avg_entry_price=90.0),
            FakePosition("WORSE", unrealized_plpc=-0.40, avg_entry_price=70.0),
        ],
        as_of=date(2026, 7, 30),
    )
    portfolio = Portfolio()

    breaches = risk.check_for_drawdown_breaches(strategy, portfolio, threshold_pct=-25.0)

    assert breaches == [
        ("BAD", -30.0, -30.0, 80.0, date(2026, 7, 30)),
        ("WORSE", -40.0, -40.0, 70.0, date(2026, 7, 30)),
    ]


def test_check_for_drawdown_breaches_skips_tickers_in_cooldown() -> None:
    """Tickers already in drawdown_reviews are not re-flagged."""
    strategy = FakeStrategy(
        positions=[
            FakePosition("AAPL", unrealized_plpc=-0.35, avg_entry_price=100.0),
            FakePosition("MSFT", unrealized_plpc=-0.40, avg_entry_price=200.0),
        ],
        as_of=date(2026, 7, 30),
    )
    portfolio = Portfolio()
    portfolio.drawdown_reviews["AAPL"] = ("AAPL", -35.0, date(2026, 7, 20))

    breaches = risk.check_for_drawdown_breaches(strategy, portfolio)

    assert breaches == [("MSFT", -40.0, -40.0, 200.0, date(2026, 7, 30))]


def test_check_for_drawdown_breaches_returns_empty_when_none() -> None:
    """No breaches when every position is above threshold."""
    strategy = FakeStrategy(
        positions=[FakePosition("AAPL", unrealized_plpc=-0.05)],
        as_of=date(2026, 7, 30),
    )

    breaches = risk.check_for_drawdown_breaches(strategy, Portfolio())

    assert breaches == []


def test_give_back_catches_round_tripped_winner(monkeypatch: pytest.MonkeyPatch) -> None:
    """A name still profitable on cost alerts once it gives back enough from its high."""
    # Bought at 100, ran to 190, now 130: +30% on cost but -31.6% off the peak.
    monkeypatch.setattr(
        risk,
        "load_daily_prices",
        lambda **_: pd.DataFrame({"date": [date(2026, 3, 2)], "close": [190.0]}),
    )
    strategy = FakeStrategy(
        positions=[
            FakePosition(
                "WINNER",
                unrealized_plpc=0.30,
                avg_entry_price=100.0,
                current_price=130.0,
            )
        ],
    )

    breaches = risk.check_for_drawdown_breaches(strategy, Portfolio(), threshold_pct=-25.0)

    assert len(breaches) == 1
    ticker, give_back, pnl_pct, _avg_entry, _as_of = breaches[0]
    assert ticker == "WINNER"
    assert give_back == -31.58
    assert pnl_pct == 30.0


def test_give_back_matches_unrealized_pnl_when_never_profitable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A position whose best mark stayed under entry alerts on its plain PnL."""
    # Best close since entry was 98 — below the 100 entry, so the floor at zero applies.
    monkeypatch.setattr(
        risk,
        "load_daily_prices",
        lambda **_: pd.DataFrame({"date": [date(2026, 3, 2)], "close": [98.0]}),
    )
    strategy = FakeStrategy(
        positions=[
            FakePosition("LOSER", unrealized_plpc=-0.30, avg_entry_price=100.0, current_price=70.0)
        ],
    )

    breaches = risk.check_for_drawdown_breaches(strategy, Portfolio(), threshold_pct=-25.0)

    # Without the entry-price floor the 98 peak would soften this to -28.6%.
    assert breaches[0][1] == -30.0
    assert breaches[0][2] == -30.0


def test_give_back_handles_shorts(monkeypatch: pytest.MonkeyPatch) -> None:
    """A short measures give-back from its lowest price, not its highest."""
    # Shorted at 100, fell to 60, now back at 90: the price rose 50% off its low.
    monkeypatch.setattr(
        risk,
        "load_daily_prices",
        lambda **_: pd.DataFrame({"date": [date(2026, 3, 2)], "close": [60.0]}),
    )
    strategy = FakeStrategy(
        positions=[
            FakePosition(
                "SHORT",
                unrealized_plpc=0.10,
                avg_entry_price=100.0,
                qty=-10.0,
                current_price=90.0,
            )
        ],
        orders={"SHORT": [FakeOrder("sell", 10.0, datetime(2026, 1, 5, tzinfo=timezone.utc))]},
    )

    breaches = risk.check_for_drawdown_breaches(strategy, Portfolio(), threshold_pct=-25.0)

    assert breaches[0][1] == -50.0


def test_entry_date_reads_the_real_alpaca_side_enum() -> None:
    """Sides arrive as OrderSide enums, whose str() is 'OrderSide.BUY', not 'buy'."""
    orders = [
        FakeOrder(OrderSide.BUY, 10.0, datetime(2026, 6, 1, tzinfo=timezone.utc)),
        FakeOrder(OrderSide.SELL, 4.0, datetime(2026, 5, 1, tzinfo=timezone.utc)),
        FakeOrder(OrderSide.BUY, 4.0, datetime(2026, 2, 1, tzinfo=timezone.utc)),
    ]
    api = SimpleNamespace(get_orders=lambda filter: orders)

    assert risk.entry_date(api, "AAPL", 10.0) == date(2026, 6, 1)


def test_entry_date_uses_most_recent_flat_point() -> None:
    """Fills before the position last went flat are ignored."""
    orders = [
        FakeOrder("buy", 10.0, datetime(2026, 6, 1, tzinfo=timezone.utc)),  # current entry
        FakeOrder("sell", 5.0, datetime(2026, 4, 1, tzinfo=timezone.utc)),  # closed prior lot
        FakeOrder("buy", 5.0, datetime(2026, 1, 5, tzinfo=timezone.utc)),  # prior lot
    ]
    api = SimpleNamespace(get_orders=lambda filter: orders)

    assert risk.entry_date(api, "AAPL", 10.0) == date(2026, 6, 1)


def test_breach_falls_back_to_pnl_when_entry_unresolved() -> None:
    """An unmatched fill history still produces a breach, on unrealized PnL."""
    strategy = FakeStrategy(
        positions=[FakePosition("ORPHAN", unrealized_plpc=-0.30, avg_entry_price=100.0)],
        orders={"ORPHAN": []},
    )

    breaches = risk.check_for_drawdown_breaches(strategy, Portfolio(), threshold_pct=-25.0)

    assert breaches[0][1] == -30.0
    assert breaches[0][2] == -30.0


#     ================================
# --> clear_expired_drawdown_reviews
#     ================================


def test_clear_expired_drawdown_reviews_removes_only_stale() -> None:
    """Reviews older than the window are dropped; recent ones stay."""
    strategy = FakeStrategy(as_of=date(2026, 7, 30))
    portfolio = Portfolio()
    portfolio.drawdown_reviews = {
        "STALE": ("STALE", -30.0, date(2026, 7, 1)),  # 29 days ago
        "FRESH": ("FRESH", -28.0, date(2026, 7, 25)),  # 5 days ago
        "EDGE": ("EDGE", -27.0, date(2026, 7, 16)),  # exactly 14 days ago — not older
    }

    stale = risk.clear_expired_drawdown_reviews(strategy, portfolio, window_days=14)

    assert stale == ["STALE"]
    assert "STALE" not in portfolio.drawdown_reviews
    assert set(portfolio.drawdown_reviews) == {"FRESH", "EDGE"}


def test_clear_expired_drawdown_reviews_noop_when_all_fresh() -> None:
    """Empty stale list when every review is inside the window."""
    strategy = FakeStrategy(as_of=date(2026, 7, 30))
    portfolio = Portfolio()
    portfolio.drawdown_reviews = {
        "AAPL": ("AAPL", -30.0, date(2026, 7, 28)),
    }

    stale = risk.clear_expired_drawdown_reviews(strategy, portfolio, window_days=14)

    assert stale == []
    assert "AAPL" in portfolio.drawdown_reviews


#     ================================
# --> review_drawdowns
#     ================================


def test_review_drawdowns_returns_decision_per_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each successful agent run yields a (breach, decision) pair."""
    agent = FakeAgent(action="exit")
    monkeypatch.setattr(risk, "build_risk_manager", lambda: agent)
    monkeypatch.setattr(risk, "MAX_WORKERS", 1)

    breaches = [_breach("AAPL"), _breach("MSFT")]

    results = risk.review_drawdowns(breaches)

    assert len(results) == 2
    assert {breach[0] for breach, _ in results} == {"AAPL", "MSFT"}
    assert all(decision.action == "exit" for _, decision in results)
    assert len(agent.tasks) == 2


def test_review_drawdowns_isolates_agent_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed ticker is omitted; other reviews still complete."""
    agent = FakeAgent(action="hold", fail_tickers={"FAIL"})
    monkeypatch.setattr(risk, "build_risk_manager", lambda: agent)
    monkeypatch.setattr(risk, "MAX_WORKERS", 1)

    breaches = [_breach("AAPL"), _breach("FAIL"), _breach("MSFT")]

    results = risk.review_drawdowns(breaches)

    assert {breach[0] for breach, _ in results} == {"AAPL", "MSFT"}


def test_review_drawdowns_empty_input_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No agent work when there are no breaches."""
    called = False

    def boom() -> None:
        nonlocal called
        called = True
        raise AssertionError("agent should not build")

    monkeypatch.setattr(risk, "build_risk_manager", boom)

    assert risk.review_drawdowns([]) == []
    assert called is False


#     ================================
# --> estimate_freed_capital
#     ================================


def test_estimate_freed_capital_sums_sells_at_last_price() -> None:
    """Freed cash is qty * last price across sized sells."""
    strategy = SimpleNamespace(
        get_last_price=lambda ticker: {"AAPL": 100.0, "MSFT": 50.5}[ticker],
    )
    sells = [
        ("AAPL", 10, "exit"),
        ("MSFT", 4, "trim 50%"),
    ]

    freed = risk.estimate_freed_capital(strategy, sells)

    assert freed == 1202.0


def test_estimate_freed_capital_skips_missing_or_invalid_prices() -> None:
    """Names without a usable last price are excluded from the total."""
    prices = {"AAPL": 100.0, "BAD": 0.0, "NONE": None}
    strategy = SimpleNamespace(get_last_price=lambda ticker: prices[ticker])
    sells = [
        ("AAPL", 5, "exit"),
        ("BAD", 3, "exit"),
        ("NONE", 2, "exit"),
    ]

    freed = risk.estimate_freed_capital(strategy, sells)

    assert freed == 500.0


def test_estimate_freed_capital_empty_sells() -> None:
    """No sells means zero freed capital."""
    strategy = SimpleNamespace(get_last_price=lambda _t: 100.0)

    assert risk.estimate_freed_capital(strategy, []) == 0.0


#     ================================
# --> manage_drawdowns (orchestration)
#     ================================


def _stub_sizing_and_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip broker sizing/submit in orchestration tests."""
    monkeypatch.setattr(risk, "size_drawdown_orders", lambda _s, _o: ([], []))
    monkeypatch.setattr(risk, "estimate_freed_capital", lambda _s, _sells: 0.0)
    monkeypatch.setattr(risk, "submit_drawdown_orders", lambda _s, _sells, _buys: None)


def test_manage_drawdowns_returns_actionable_orders_and_records_successes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Actionable decisions are returned; completed reviews start cooldown."""
    strategy = FakeStrategy(
        positions=[
            FakePosition("TRIM", unrealized_plpc=-0.30, avg_entry_price=50.0),
            FakePosition("HOLD", unrealized_plpc=-0.35, avg_entry_price=60.0),
            FakePosition("EXIT", unrealized_plpc=-0.40, avg_entry_price=70.0),
            FakePosition("OK", unrealized_plpc=-0.05, avg_entry_price=80.0),
        ],
        as_of=date(2026, 7, 30),
    )
    portfolio = Portfolio()
    agent = FakeAgent(
        action_by_ticker={
            "TRIM": ("trim", 0.5),
            "HOLD": ("hold", None),
            "EXIT": ("exit", None),
        }
    )
    monkeypatch.setattr(risk, "build_risk_manager", lambda: agent)
    monkeypatch.setattr(risk, "MAX_WORKERS", 1)
    _stub_sizing_and_submit(monkeypatch)

    orders = risk.manage_drawdowns(strategy, portfolio)

    assert {breach[0] for breach, _ in orders} == {"TRIM", "EXIT"}
    assert all(decision.action in {"trim", "exit", "add"} for _, decision in orders)
    # All successful agent runs enter cooldown, including hold.
    assert set(portfolio.drawdown_reviews) == {"TRIM", "HOLD", "EXIT"}
    assert "OK" not in portfolio.drawdown_reviews


def test_manage_drawdowns_returns_empty_when_no_breaches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No agent work and no cooldown writes when nothing is under threshold."""
    strategy = FakeStrategy(
        positions=[FakePosition("AAPL", unrealized_plpc=-0.05)],
        as_of=date(2026, 7, 30),
    )
    portfolio = Portfolio()

    def boom() -> None:
        raise AssertionError("agent should not run")

    monkeypatch.setattr(risk, "build_risk_manager", boom)

    orders = risk.manage_drawdowns(strategy, portfolio)

    assert orders == []
    assert portfolio.drawdown_reviews == {}


def test_manage_drawdowns_does_not_record_failed_reviews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed agent runs stay eligible for a later breach check."""
    strategy = FakeStrategy(
        positions=[
            FakePosition("GOOD", unrealized_plpc=-0.30, avg_entry_price=50.0),
            FakePosition("BAD", unrealized_plpc=-0.35, avg_entry_price=60.0),
        ],
        as_of=date(2026, 7, 30),
    )
    portfolio = Portfolio()
    agent = FakeAgent(action="exit", fail_tickers={"BAD"})
    monkeypatch.setattr(risk, "build_risk_manager", lambda: agent)
    monkeypatch.setattr(risk, "MAX_WORKERS", 1)
    _stub_sizing_and_submit(monkeypatch)

    orders = risk.manage_drawdowns(strategy, portfolio)

    assert len(orders) == 1
    assert orders[0][0][0] == "GOOD"
    assert set(portfolio.drawdown_reviews) == {"GOOD"}
    assert "BAD" not in portfolio.drawdown_reviews
