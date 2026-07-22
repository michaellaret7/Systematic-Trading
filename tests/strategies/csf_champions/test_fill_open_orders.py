"""Prove the sweep cannot duplicate orders that are already working or filled.

Replays the 2026-07-21 incident: entry orders submitted seconds earlier, their
fills dropped by Lumibot's first-iteration event blackout (ledger rows still
read 0 filled), and Alpaca's laggy order-list endpoint unable to report the
fresh orders. The old sweep re-submitted 39 full-size duplicates; the
reconciling sweep must submit none, and must never ask the laggy broker list.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from systematic_trading.strategies.csf_champions.workflows import fill_open_orders as sweep


def open_row(symbol: str, target: int, filled: int = 0) -> dict:
    """One open ledger row as load_open_orders returns it."""
    return {
        "trade_id": f"2026-07-21T15:25:00+00:00#{symbol}#abcd1234",
        "symbol": symbol,
        "target_quantity": target,
        "filled_quantity": filled,
    }


class FakeOrder:
    """Order shape the sweep reads: asset.symbol, side check, identifier."""

    def __init__(self, symbol: str, quantity: int = 0) -> None:
        self.asset = SimpleNamespace(symbol=symbol)
        self.identifier = f"order-{symbol}"
        self.quantity = quantity

    def is_buy_order(self) -> bool:
        return True


class FakeStrategy:
    """Broker state frozen at a moment in time, with submissions captured."""

    def __init__(
        self,
        working: set[str],
        positions: dict[str, tuple[int, float]],
    ) -> None:
        self._working = working
        self._positions = positions
        self.get_orders_refresh_args: list[bool] = []
        self.submitted: list[tuple[str, int]] = []
        self.order_trade_ids: dict[str, str] = {}

    def get_orders(self, statuses: object = None, broker_refresh: bool = True) -> list[FakeOrder]:
        self.get_orders_refresh_args.append(broker_refresh)

        return [FakeOrder(symbol) for symbol in sorted(self._working)]

    def get_position(self, symbol: str) -> SimpleNamespace | None:
        if symbol not in self._positions:
            return None

        quantity, avg_price = self._positions[symbol]

        return SimpleNamespace(quantity=quantity, avg_fill_price=avg_price)

    def get_datetime(self) -> datetime:
        return datetime(2026, 7, 21, 15, 26, tzinfo=timezone.utc)

    # Pricing calls are reached only when a genuine remainder is re-submitted.
    def get_quote(self, ticker: str) -> SimpleNamespace:
        return SimpleNamespace(ask=10.0)

    def get_last_price(self, ticker: str) -> float:
        return 10.0

    def create_order(
        self,
        symbol: str,
        quantity: int,
        side: str,
        limit_price: float | None = None,
        time_in_force: str | None = None,
    ) -> FakeOrder:
        return FakeOrder(symbol, quantity)

    def submit_order(self, order: FakeOrder) -> None:
        self.submitted.append((order.asset.symbol, order.quantity))


@pytest.fixture()
def ledger_spy(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Capture ledger heals and idea flips; completion mirrors the real contract."""
    calls: dict = {"healed": [], "flipped": []}
    targets: dict[str, int] = {}

    def fake_load_open_orders(strategy: str) -> pd.DataFrame:
        raise AssertionError("each test monkeypatches its own rows")

    def fake_sync_fill(
        strategy: str,
        trade_id: str,
        filled_quantity: int,
        avg_price: float,
        filled_at: datetime,
    ) -> str | None:
        calls["healed"].append((trade_id, filled_quantity, avg_price))

        completed = filled_quantity >= targets[trade_id]

        return f"idea-{trade_id}" if completed else None

    def fake_update_idea_status(strategy: str, idea_id: str, status: str) -> None:
        calls["flipped"].append((idea_id, status))

    calls["targets"] = targets

    monkeypatch.setattr(sweep, "load_open_orders", fake_load_open_orders)
    monkeypatch.setattr(sweep, "sync_fill", fake_sync_fill)
    monkeypatch.setattr(sweep, "update_idea_status", fake_update_idea_status)

    return calls


def set_rows(monkeypatch: pytest.MonkeyPatch, ledger_spy: dict, rows: list[dict]) -> None:
    """Install the open rows and register their targets with the fake ledger."""
    for row in rows:
        ledger_spy["targets"][row["trade_id"]] = int(row["target_quantity"])

    frame = pd.DataFrame(rows)

    monkeypatch.setattr(sweep, "load_open_orders", lambda strategy: frame)


def test_startup_blackout_submits_zero_duplicates(
    monkeypatch: pytest.MonkeyPatch, ledger_spy: dict
) -> None:
    """The incident: ledger reads 0 filled, yet every order is working or filled.

    AUPH's entry order is still live, MELI's already filled completely, and
    HRMY is partially filled with its order still live. The old sweep sent
    full-size duplicates for all three; the reconciling sweep must send none.
    """
    set_rows(
        monkeypatch,
        ledger_spy,
        [
            open_row("AUPH", 637),
            open_row("MELI", 5),
            open_row("HRMY", 269),
        ],
    )

    strategy = FakeStrategy(
        working={"AUPH", "HRMY"},
        positions={"MELI": (5, 10.0), "HRMY": (51, 38.0)},
    )

    sweep.fill_open_orders(strategy)

    # The proof: not a single order was submitted.
    assert strategy.submitted == []

    # And the laggy broker order list was never consulted.
    assert strategy.get_orders_refresh_args == [False]

    # MELI's missed fill was healed from the position and its idea flipped.
    assert ("2026-07-21T15:25:00+00:00#MELI#abcd1234", 5, 10.0) in ledger_spy["healed"]
    assert ("idea-2026-07-21T15:25:00+00:00#MELI#abcd1234", "filled") in ledger_spy["flipped"]

    # HRMY healed to the broker's 51 but stays open (order still working).
    assert ("2026-07-21T15:25:00+00:00#HRMY#abcd1234", 51, 38.0) in ledger_spy["healed"]


def test_morning_remainder_is_sized_from_broker_truth(
    monkeypatch: pytest.MonkeyPatch, ledger_spy: dict
) -> None:
    """Next morning: no working orders, ledger stale at 143, broker holds 1200.

    The re-submit must be target - position (274 shares), not target - stale
    ledger (1331) â€” over-buying past target is impossible even with a stale
    ledger.
    """
    set_rows(monkeypatch, ledger_spy, [open_row("FSM", 1474, filled=143)])

    strategy = FakeStrategy(working=set(), positions={"FSM": (1200, 8.5)})

    sweep.fill_open_orders(strategy)

    assert strategy.submitted == [("FSM", 274)]

    # The new order maps to the existing ledger row, not a new one.
    assert strategy.order_trade_ids == {"order-FSM": "2026-07-21T15:25:00+00:00#FSM#abcd1234"}


def test_fully_healed_row_is_closed_without_any_order(
    monkeypatch: pytest.MonkeyPatch, ledger_spy: dict
) -> None:
    """A row whose position already meets target is closed, never re-submitted."""
    set_rows(monkeypatch, ledger_spy, [open_row("DG", 80)])

    strategy = FakeStrategy(working=set(), positions={"DG": (80, 123.71)})

    sweep.fill_open_orders(strategy)

    assert strategy.submitted == []
    assert ("idea-2026-07-21T15:25:00+00:00#DG#abcd1234", "filled") in ledger_spy["flipped"]
