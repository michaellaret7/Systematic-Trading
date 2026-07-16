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

import pandas as pd

from systematic_trading.data.price_sync import YEARS_OF_HISTORY, fetch_symbols
from systematic_trading.data.providers.fmp import FMPClient
from systematic_trading.data.repository import (
    daily_prices_uri,
    load_daily_prices,
    panel_symbols,
    write_daily_prices,
)

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

    frames, failures = fetch_symbols(client, symbols, start, end, "full")

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
