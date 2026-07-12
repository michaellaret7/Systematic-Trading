"""Build the daily price file of the S3 prices repository.

Universe: every symbol in the fundamentals panel. For each symbol, fetch the
last 4 years of split-adjusted daily OHLCV bars from FMP (the ``close`` column
is the split-adjusted close) and write the whole universe in one shot to
s3://<S3_BUCKET>/prices/daily_ohclv.parquet.

Full refresh: the parquet is replaced wholesale per run, so reruns are
idempotent and never accumulate stale symbols.

Usage:
    uv run python scripts/push_daily_prices.py
"""

from __future__ import annotations

import datetime as dt
import time

import pandas as pd
import requests

from systematic_trading.data.providers.fmp import FMPClient
from systematic_trading.data.repository import (
    daily_prices_uri,
    load_daily_prices,
    panel_symbols,
    write_daily_prices,
)

YEARS_OF_HISTORY = 4

RETRIES = 5
BACKOFF_BASE_S = 2.0  # exponential: 2s, 4s, 8s, 16s between attempts

# RuntimeError covers FMP-level errors from FMPClient; RequestException covers
# network-level failures (connection resets, timeouts) that long runs will hit.
TRANSIENT_ERRORS = (RuntimeError, requests.RequestException)

#     ================================
# --> Helper funcs
#     ================================


def fetch_with_backoff(
    client: FMPClient, symbol: str, start: dt.date, end: dt.date
) -> pd.DataFrame:
    """One symbol's daily bars; retries transient errors with exponential backoff."""
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
    """Tz-aware OHLCV frame -> flat (symbol, date, open, high, low, close, volume) rows."""
    rows = bars.reset_index()
    rows["date"] = rows["date"].dt.tz_localize(None)

    rows.insert(0, "symbol", symbol)

    return rows


def fetch_symbols(
    client: FMPClient, symbols: list[str], start: dt.date, end: dt.date, label: str
) -> tuple[list[pd.DataFrame], list[str]]:
    """Daily bars for each symbol as flat panel rows; returns (frames, failed symbols)."""
    frames: list[pd.DataFrame] = []
    failures: list[str] = []

    for i, symbol in enumerate(symbols, start=1):
        try:
            bars = fetch_with_backoff(client, symbol, start, end)
        except TRANSIENT_ERRORS as error:
            failures.append(symbol)
            print(f"  {symbol}: giving up ({error})")
            continue

        if not bars.empty:
            frames.append(to_panel_rows(symbol, bars))

        if i % 250 == 0:
            print(f"  [{label}] {i}/{len(symbols)} symbols fetched...")

    return frames, failures


#     ================================
# --> Entry point
#     ================================


def main() -> None:
    client = FMPClient()
    symbols = panel_symbols()

    end = dt.date.today()
    start = end - dt.timedelta(days=YEARS_OF_HISTORY * 365)

    print(f"Universe: {len(symbols)} symbols from the fundamentals panel.")
    print(f"Range: {start} -> {end} (split-adjusted daily bars).")

    frames: list[pd.DataFrame] = []
    failures: list[str] = []

    for i, symbol in enumerate(symbols, start=1):
        try:
            bars = fetch_with_backoff(client, symbol, start, end)
        except TRANSIENT_ERRORS as error:
            failures.append(symbol)
            print(f"  {symbol}: giving up ({error})")
            continue

        if not bars.empty:
            frames.append(to_panel_rows(symbol, bars))

        if i % 250 == 0:
            print(f"  {i}/{len(symbols)} symbols fetched...")

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values(["symbol", "date"], ignore_index=True)

    uri = daily_prices_uri()

    print(
        f"Writing {len(combined):,} rows x {combined.shape[1]} columns "
        f"for {combined['symbol'].nunique():,} symbols to {uri} ..."
    )
    write_daily_prices(combined)

    # Read back from S3 so the round trip is verified, not assumed.
    check = load_daily_prices(columns=["symbol", "date"])

    print(
        f"Read-back: {len(check):,} rows, {check['symbol'].nunique():,} symbols, "
        f"{check['date'].min().date()} -> {check['date'].max().date()}"
    )

    if failures:
        print(f"Failed symbols ({len(failures)}): {', '.join(failures)}")


if __name__ == "__main__":
    main()
