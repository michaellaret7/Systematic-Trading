"""Ledger reconcile against broker fills."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from systematic_trading.portfolio import reconcile as reconcile_module
from systematic_trading.portfolio.reconcile import reconcile_open_orders


def test_reconcile_closes_row_via_broker_order_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rows with broker_order_id finalize when Alpaca shows filled."""
    finalized: list[dict] = []

    monkeypatch.setattr(
        reconcile_module,
        "load_open_orders",
        lambda strategy_name: [
            {
                "trade_id": "trade-gddy",
                "symbol": "GDDY",
                "side": "buy",
                "target_quantity": 146,
                "broker_order_id": "oid-1",
            }
        ],
    )
    monkeypatch.setattr(
        reconcile_module,
        "finalize_filled_trade",
        lambda strategy_name, trade_id, **kwargs: finalized.append(
            {"strategy": strategy_name, "trade_id": trade_id, **kwargs}
        )
        or "idea-gddy",
    )
    monkeypatch.setattr(reconcile_module.log, "info", lambda *a, **k: None)
    monkeypatch.setattr(reconcile_module.log, "warning", lambda *a, **k: None)

    api = SimpleNamespace(
        get_order_by_id=lambda order_id: SimpleNamespace(
            status="filled",
            filled_avg_price="99.50",
            filled_qty="146",
            symbol="GDDY",
            side="buy",
            filled_at=datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc),
        )
    )
    strategy = SimpleNamespace(
        broker=SimpleNamespace(api=api),
        get_datetime=lambda: datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc),
        get_position=lambda symbol: SimpleNamespace(quantity=146, avg_fill_price=99.5),
    )

    count = reconcile_open_orders(strategy, "csf_champions")

    assert count == 1
    assert finalized[0]["trade_id"] == "trade-gddy"
    assert finalized[0]["average_fill_price"] == 99.5
    assert finalized[0]["symbol"] == "GDDY"


def test_reconcile_matches_legacy_rows_without_broker_order_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy open rows match closed broker orders by symbol and side."""
    finalized: list[str] = []

    monkeypatch.setattr(
        reconcile_module,
        "load_open_orders",
        lambda strategy_name: [
            {
                "trade_id": "trade-aapl",
                "symbol": "AAPL",
                "side": "buy",
                "target_quantity": 40,
            }
        ],
    )
    monkeypatch.setattr(
        reconcile_module,
        "finalize_filled_trade",
        lambda strategy_name, trade_id, **kwargs: finalized.append(trade_id) or None,
    )
    monkeypatch.setattr(
        reconcile_module,
        "_closed_orders_by_symbol",
        lambda api: {
            "AAPL": [
                SimpleNamespace(
                    status="filled",
                    filled_avg_price="100",
                    filled_qty="40",
                    symbol="AAPL",
                    side="buy",
                    filled_at=datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc),
                )
            ]
        },
    )
    monkeypatch.setattr(reconcile_module.log, "info", lambda *a, **k: None)

    api = SimpleNamespace(get_order_by_id=lambda order_id: None)
    strategy = SimpleNamespace(
        broker=SimpleNamespace(api=api),
        get_datetime=lambda: datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc),
        get_position=lambda symbol: None,
    )

    count = reconcile_open_orders(strategy, "csf_champions")

    assert count == 1
    assert finalized == ["trade-aapl"]


def test_reconcile_skips_unfilled_broker_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    """Open broker orders do not close ledger rows."""
    monkeypatch.setattr(
        reconcile_module,
        "load_open_orders",
        lambda strategy_name: [
            {
                "trade_id": "trade-msft",
                "symbol": "MSFT",
                "side": "buy",
                "target_quantity": 10,
                "broker_order_id": "oid-open",
            }
        ],
    )
    monkeypatch.setattr(
        reconcile_module,
        "finalize_filled_trade",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not finalize")),
    )
    monkeypatch.setattr(reconcile_module.log, "info", lambda *a, **k: None)

    api = SimpleNamespace(
        get_order_by_id=lambda order_id: SimpleNamespace(
            status="new",
            filled_avg_price=None,
            filled_qty="0",
            symbol="MSFT",
            side="buy",
        )
    )
    strategy = SimpleNamespace(
        broker=SimpleNamespace(api=api),
        get_datetime=lambda: datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc),
        get_position=lambda symbol: None,
    )

    assert reconcile_open_orders(strategy, "csf_champions") == 0
