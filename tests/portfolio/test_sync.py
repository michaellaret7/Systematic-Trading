"""Shared portfolio fill/mark sync used by every strategy sleeve."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from systematic_trading.portfolio import sync as sync_module
from systematic_trading.portfolio.sync import (
    normalize_symbol,
    position_side,
    sync_portfolio_from_fill,
    sync_position_pnl,
)


def test_position_side_prefers_broker_side_over_sign() -> None:
    """Alpaca enums/strings win; signed qty is only a fallback."""
    assert position_side(SimpleNamespace(side="short"), signed_qty=10.0) == "short"
    assert position_side(SimpleNamespace(side="LONG"), signed_qty=-10.0) == "long"
    assert position_side(SimpleNamespace(side=None), signed_qty=-5.0) == "short"
    assert position_side(SimpleNamespace(), signed_qty=5.0) == "long"


def test_normalize_symbol_maps_crypto_pairs_to_base() -> None:
    """Alpaca crypto pairs collapse to the base asset we store in Dynamo."""
    assert normalize_symbol("btcusd") == "BTC"
    assert normalize_symbol("ETHUSD") == "ETH"
    assert normalize_symbol("AAPL") == "AAPL"
    assert normalize_symbol("BTC") == "BTC"


def test_sync_portfolio_from_fill_upserts_absolute_short_qty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shorts store positive quantity with side=short, never negative qty."""
    calls: list[dict] = []

    monkeypatch.setattr(
        sync_module,
        "apply_broker_position",
        lambda strategy_name, symbol, **kwargs: calls.append(
            {"strategy": strategy_name, "symbol": symbol, **kwargs}
        ),
    )
    monkeypatch.setattr(
        sync_module,
        "delete_position",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not delete")),
    )

    sync_portfolio_from_fill(
        "csf_champions",
        SimpleNamespace(quantity=-40, side="short", avg_fill_price=50.0),
        symbol="AAPL",
        idea_id="idea-aapl",
        filled_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )

    assert calls == [
        {
            "strategy": "csf_champions",
            "symbol": "AAPL",
            "quantity": 40.0,
            "side": "short",
            "avg_cost": 50.0,
            "now": datetime(2026, 7, 30, tzinfo=timezone.utc),
            "idea_id": "idea-aapl",
        }
    ]


def test_sync_portfolio_from_fill_keeps_fractional_crypto_qty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fractional sizes (e.g. 0.001 BTC) are not truncated to zero."""
    calls: list[dict] = []

    monkeypatch.setattr(
        sync_module,
        "apply_broker_position",
        lambda strategy_name, symbol, **kwargs: calls.append(
            {"strategy": strategy_name, "symbol": symbol, **kwargs}
        ),
    )

    sync_portfolio_from_fill(
        "btc_ticker",
        SimpleNamespace(quantity=0.001, side="long", avg_fill_price=95_000.0),
        symbol="BTC",
        filled_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )

    assert calls[0]["quantity"] == 0.001
    assert calls[0]["strategy"] == "btc_ticker"


def test_sync_portfolio_from_fill_deletes_when_flat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flat broker size removes the strategy portfolio row."""
    deletes: list[tuple[str, str]] = []

    monkeypatch.setattr(
        sync_module,
        "delete_position",
        lambda strategy_name, symbol: deletes.append((strategy_name, symbol)),
    )
    monkeypatch.setattr(
        sync_module,
        "apply_broker_position",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not upsert")),
    )

    sync_portfolio_from_fill(
        "other_sleeve",
        SimpleNamespace(quantity=0, side="long", avg_fill_price=10.0),
        symbol="MSFT",
        filled_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )

    assert deletes == [("other_sleeve", "MSFT")]


def test_sync_position_pnl_joins_book_to_alpaca(monkeypatch: pytest.MonkeyPatch) -> None:
    """PnL marks are written only for symbols present at the broker."""
    mark_calls: list = []
    warnings: list[str] = []

    monkeypatch.setattr(
        sync_module,
        "load_positions",
        lambda strategy_name: pd.DataFrame(
            [
                {"strategy": strategy_name, "symbol": "AAPL"},
                {"strategy": strategy_name, "symbol": "MSFT"},
            ]
        ),
    )
    monkeypatch.setattr(sync_module, "update_marks", lambda marks: mark_calls.append(marks))
    monkeypatch.setattr(
        sync_module.log,
        "warning",
        lambda message, *args: warnings.append(message % args if args else message),
    )
    monkeypatch.setattr(sync_module.log, "info", lambda *a, **k: None)

    runner = SimpleNamespace(
        broker=SimpleNamespace(
            api=SimpleNamespace(
                get_all_positions=lambda: [
                    SimpleNamespace(
                        symbol="AAPL",
                        unrealized_pl=12.5,
                        unrealized_plpc=0.025,
                        current_price=205.0,
                        market_value=8200.0,
                    )
                ]
            )
        ),
        get_datetime=lambda: datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc),
    )

    sync_position_pnl(runner, "csf_champions")

    assert len(mark_calls) == 1
    assert mark_calls[0].symbol == "AAPL"
    assert mark_calls[0].unrealized_plpc == 0.025
    assert any("MSFT" in message for message in warnings)


def test_sync_position_pnl_joins_btc_book_to_btcusd_broker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Book rows keyed as BTC still pick up Alpaca BTCUSD marks."""
    mark_calls: list = []

    monkeypatch.setattr(
        sync_module,
        "load_positions",
        lambda strategy_name: pd.DataFrame(
            [{"strategy": strategy_name, "symbol": "BTC"}]
        ),
    )
    monkeypatch.setattr(sync_module, "update_marks", lambda marks: mark_calls.append(marks))
    monkeypatch.setattr(sync_module.log, "info", lambda *a, **k: None)
    monkeypatch.setattr(sync_module.log, "warning", lambda *a, **k: None)

    runner = SimpleNamespace(
        broker=SimpleNamespace(
            api=SimpleNamespace(
                get_all_positions=lambda: [
                    SimpleNamespace(
                        symbol="BTCUSD",
                        unrealized_pl=-0.05,
                        unrealized_plpc=-0.0007,
                        current_price=64736.97,
                        market_value=62.8,
                    )
                ]
            )
        ),
        get_datetime=lambda: datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc),
    )

    sync_position_pnl(runner, "btc_ticker")

    assert len(mark_calls) == 1
    assert mark_calls[0].strategy == "btc_ticker"
    assert mark_calls[0].symbol == "BTC"
    assert mark_calls[0].current_price == 64736.97
    assert mark_calls[0].unrealized_plpc == -0.0007
