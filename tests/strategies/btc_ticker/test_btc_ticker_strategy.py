"""BTC ticker broker lifecycle hooks (ledger + portfolio sync)."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from systematic_trading.strategies.btc_ticker import strategy as strategy_module
from systematic_trading.strategies.btc_ticker.strategy import (
    ALPACA_MIN_NOTIONAL_USD,
    NOTIONAL_BUFFER,
    BtcTicker,
    iteration_quantity,
)


class FilledHookContext:
    """Minimal strategy state required by ``on_filled_order``."""

    is_backtesting = False
    trade_ids_by_order_id = {"alpaca-order-btc": "trade-btc"}

    @staticmethod
    def get_datetime() -> datetime:
        """Return a stable fill timestamp."""
        return datetime(2026, 7, 30, 9, 31, tzinfo=timezone.utc)


class IterationContext:
    """Minimal strategy state required by ``on_trading_iteration``."""

    is_backtesting = False
    ticks = 0
    base = SimpleNamespace(symbol="BTC")
    quote = SimpleNamespace(symbol="USD")
    parameters = {"quantity": 0.00001}
    trade_ids_by_order_id: dict[str, str]
    submitted: list
    held_qty: float
    last_price: float
    _order_seq: int

    def __init__(self, *, held_qty: float = 0.0, last_price: float = 64_806.14) -> None:
        self.trade_ids_by_order_id = {}
        self.submitted = []
        self.held_qty = held_qty
        self.last_price = last_price
        self._order_seq = 0

    def get_position(self, asset):  # noqa: ANN001
        if self.held_qty <= 0:
            return None

        return SimpleNamespace(
            quantity=self.held_qty,
            avg_fill_price=100_000.0,
            pnl=0.0,
            to_minimal_dict=lambda: {"qty": self.held_qty},
        )

    def get_portfolio_value(self) -> float:
        return 100_000.0

    def get_cash(self) -> float:
        return 50_000.0

    def get_last_price(self, asset, quote=None):  # noqa: ANN001
        return self.last_price

    def get_datetime(self) -> datetime:
        return datetime(2026, 7, 30, 9, 31, tzinfo=timezone.utc)

    def create_order(self, *args, **kwargs):  # noqa: ANN001
        self._order_seq += 1
        side = args[2] if len(args) > 2 else kwargs.get("side", "buy")
        quantity = args[1] if len(args) > 1 else kwargs.get("quantity")

        return SimpleNamespace(
            identifier=f"order-{self._order_seq}",
            side=side,
            quantity=quantity,
            args=args,
            kwargs=kwargs,
        )

    def submit_order(self, order) -> None:  # noqa: ANN001
        self.submitted.append(order)


def test_filled_hook_completes_ledger_and_portfolio(monkeypatch: pytest.MonkeyPatch) -> None:
    """Final fill closes the ledger row and delegates portfolio book sync."""
    completion_calls: list[tuple] = []
    portfolio_calls: list[dict] = []

    def fake_complete_order(
        strategy_name: str,
        trade_id: str,
        average_fill_price: float,
        filled_at: datetime,
    ) -> str | None:
        completion_calls.append((strategy_name, trade_id, average_fill_price, filled_at))
        return None

    def fake_sync_portfolio_from_fill(strategy_name: str, broker_position, **kwargs) -> None:
        portfolio_calls.append(
            {"strategy": strategy_name, "broker_position": broker_position, **kwargs}
        )

    monkeypatch.setattr(strategy_module, "complete_order", fake_complete_order)
    monkeypatch.setattr(strategy_module, "sync_portfolio_from_fill", fake_sync_portfolio_from_fill)

    order = SimpleNamespace(
        asset=SimpleNamespace(symbol="BTC"),
        identifier="alpaca-order-btc",
        avg_fill_price=95_000.0,
    )
    broker_position = SimpleNamespace(quantity=0.0002, side="long", avg_fill_price=95_000.0)
    context = FilledHookContext()

    BtcTicker.on_filled_order(
        context,
        position=broker_position,
        order=order,
        price=95_000.0,
        quantity=0.0002,
        multiplier=1.0,
    )

    assert completion_calls[0][1] == "trade-btc"
    assert portfolio_calls[0]["symbol"] == "BTC"
    assert "idea_id" not in portfolio_calls[0]
    assert context.trade_ids_by_order_id == {}


def test_iteration_quantity_lifts_to_alpaca_min_notional() -> None:
    """Tiny configured sizes are raised so notional clears Alpaca's $10 floor."""
    context = IterationContext(last_price=64_806.14)
    context.ticks = 1

    quantity = iteration_quantity(context)
    assert quantity is not None
    assert quantity * 64_806.14 >= ALPACA_MIN_NOTIONAL_USD
    assert quantity == pytest.approx(
        (ALPACA_MIN_NOTIONAL_USD * NOTIONAL_BUFFER) / 64_806.14
    )


def test_trading_iteration_buys_each_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-5th ticks only submit one sized BTC buy."""
    recorded: list = []

    monkeypatch.setattr(strategy_module, "sync_position_pnl", lambda *a, **k: None)
    monkeypatch.setattr(
        strategy_module,
        "record_order",
        lambda order: recorded.append(order) or f"trade-{len(recorded)}",
    )
    monkeypatch.setattr(strategy_module.log, "info", lambda *a, **k: None)
    monkeypatch.setattr(strategy_module.log, "warning", lambda *a, **k: None)

    context = IterationContext(held_qty=0.0)
    BtcTicker.on_trading_iteration(context)

    assert [order.side for order in recorded] == ["buy"]
    assert recorded[0].target_quantity * context.last_price >= ALPACA_MIN_NOTIONAL_USD
    assert len(context.submitted) == 1


def test_trading_iteration_sells_every_fifth_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every 5th tick submits buy then sell when the position can cover it."""
    recorded: list = []

    monkeypatch.setattr(strategy_module, "sync_position_pnl", lambda *a, **k: None)
    monkeypatch.setattr(
        strategy_module,
        "record_order",
        lambda order: recorded.append(order) or f"trade-{len(recorded)}",
    )
    monkeypatch.setattr(strategy_module.log, "info", lambda *a, **k: None)
    monkeypatch.setattr(strategy_module.log, "warning", lambda *a, **k: None)

    context = IterationContext(held_qty=1.0, last_price=64_806.14)
    context.ticks = 4  # next iteration becomes tick 5
    BtcTicker.on_trading_iteration(context)

    assert [order.side for order in recorded] == ["buy", "sell"]
    assert len(context.submitted) == 2
