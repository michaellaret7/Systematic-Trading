"""Shared price synchronization behavior."""

import datetime as dt

import pandas as pd
import pytest

from systematic_trading.data import price_sync


class FakeClient:
    """FMP stand-in returning configured price frames or failures."""

    def __init__(self, responses: list[pd.DataFrame | Exception]) -> None:
        self._responses = iter(responses)

    def daily_prices(
        self,
        symbol: str,
        start: dt.date,
        end: dt.date,
        adjustment: str,
    ) -> pd.DataFrame:
        """Return the next configured response."""
        response = next(self._responses)

        if isinstance(response, Exception):
            raise response

        return response


def price_frame() -> pd.DataFrame:
    """One valid tz-aware price row in the provider shape."""
    index = pd.DatetimeIndex(["2026-01-02 16:00"], tz="America/New_York", name="date")

    return pd.DataFrame(
        {"open": [100.0], "high": [102.0], "low": [99.0], "close": [101.0], "volume": [1_000]},
        index=index,
    )


def test_to_panel_rows_flattens_provider_frame() -> None:
    """Provider bars become normalized repository rows."""
    rows = price_sync.to_panel_rows("AAPL", price_frame())

    assert rows.columns.tolist() == ["symbol", "date", "open", "high", "low", "close", "volume"]
    assert rows.loc[0, "symbol"] == "AAPL"
    assert rows["date"].dt.tz is None


def test_fetch_with_backoff_retries_transient_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transient provider failures retry without sleeping in the test."""
    client = FakeClient([RuntimeError("temporary"), price_frame()])
    waits: list[float] = []
    monkeypatch.setattr(price_sync.time, "sleep", waits.append)

    result = price_sync.fetch_with_backoff(
        client,  # type: ignore[arg-type]
        "AAPL",
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 3),
    )

    assert len(result) == 1
    assert waits == [price_sync.BACKOFF_BASE_S]


def test_fetch_symbols_isolates_failed_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed symbol does not discard successful symbols in the same batch."""
    responses = {"AAPL": price_frame(), "FAIL": RuntimeError("failed")}

    def fake_fetch(
        client: FakeClient,
        symbol: str,
        start: dt.date,
        end: dt.date,
    ) -> pd.DataFrame:
        response = responses[symbol]

        if isinstance(response, Exception):
            raise response

        return response

    monkeypatch.setattr(price_sync, "fetch_with_backoff", fake_fetch)

    frames, failures = price_sync.fetch_symbols(
        FakeClient([]),  # type: ignore[arg-type]
        ["AAPL", "FAIL"],
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 3),
        "test",
    )

    assert len(frames) == 1
    assert frames[0]["symbol"].tolist() == ["AAPL"]
    assert failures == ["FAIL"]
