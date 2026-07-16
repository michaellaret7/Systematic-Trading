"""Shared FMP price-fetching behavior for full and incremental sync jobs."""

import datetime as dt
import time

import pandas as pd
import requests

from systematic_trading.data.providers.fmp import FMPClient

YEARS_OF_HISTORY = 4
RETRIES = 5
BACKOFF_BASE_S = 2.0  # exponential: 2s, 4s, 8s, 16s between attempts

# RuntimeError covers FMP-level errors from FMPClient; RequestException covers
# network-level failures (connection resets, timeouts) that long runs will hit.
TRANSIENT_ERRORS = (RuntimeError, requests.RequestException)


def fetch_with_backoff(
    client: FMPClient, symbol: str, start: dt.date, end: dt.date
) -> pd.DataFrame:
    """Fetch one symbol's daily bars, retrying transient failures with backoff."""
    for attempt in range(1, RETRIES + 1):
        try:
            return client.daily_prices(symbol, start, end, adjustment="split")
        except TRANSIENT_ERRORS as error:
            if attempt == RETRIES:
                raise

            wait = BACKOFF_BASE_S * 2 ** (attempt - 1)

            print(f"  {symbol}: attempt {attempt} failed ({error}); retrying in {wait:.0f}s...")
            time.sleep(wait)

    raise AssertionError("unreachable")


def to_panel_rows(symbol: str, bars: pd.DataFrame) -> pd.DataFrame:
    """Convert a tz-aware OHLCV frame into flat daily-price panel rows."""
    rows = bars.reset_index()
    rows["date"] = rows["date"].dt.tz_localize(None)

    rows.insert(0, "symbol", symbol)

    return rows


def fetch_symbols(
    client: FMPClient,
    symbols: list[str],
    start: dt.date,
    end: dt.date,
    label: str,
) -> tuple[list[pd.DataFrame], list[str]]:
    """Fetch flat daily-price frames and failed symbols for one symbol batch."""
    frames: list[pd.DataFrame] = []
    failures: list[str] = []

    for index, symbol in enumerate(symbols, start=1):
        try:
            bars = fetch_with_backoff(client, symbol, start, end)
        except TRANSIENT_ERRORS as error:
            failures.append(symbol)
            print(f"  {symbol}: giving up ({error})")
            continue

        if not bars.empty:
            frames.append(to_panel_rows(symbol, bars))

        if index % 250 == 0:
            print(f"  [{label}] {index}/{len(symbols)} symbols fetched...")

    return frames, failures
