"""Incrementally update the daily price file of the S3 prices repository.

Reads prices/daily_ohclv.parquet, pulls only what is missing, and rewrites it:

- Gap rows: every fundamentals-panel symbol from the day after the file's
  last date through today.
- Split re-pulls: a split retroactively changes a symbol's whole adjusted
  history, so symbols with a split inside the gap are re-fetched in full.
- New symbols: panel symbols absent from the file are backfilled in full.

The window rolls forward: rows older than YEARS_OF_HISTORY are dropped, so
the file always spans the trailing 4 years. Rerunning on an up-to-date file
is a no-op.

Usage:
    uv run python scripts/update_daily_prices.py
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
# --> Helper funcs
#     ================================


def split_symbols(client: FMPClient, start: dt.date, end: dt.date) -> set[str]:
    """Symbols with a stock split dated within [start, end]."""
    if start > end:
        return set()

    splits = client.splits_calendar(start, end)

    if splits.empty:
        return set()

    return set(splits["symbol"])


#     ================================
# --> Entry point
#     ================================


def main() -> None:
    client = FMPClient()
    symbols = panel_symbols()
    uri = daily_prices_uri()

    existing = load_daily_prices()
    last_date = existing["date"].max().date()

    today = dt.date.today()
    window_start = today - dt.timedelta(days=YEARS_OF_HISTORY * 365)
    gap_start = last_date + dt.timedelta(days=1)

    known = set(existing["symbol"].unique())
    new_symbols = sorted(set(symbols) - known)
    resplit = sorted(split_symbols(client, gap_start, today) & known)

    full_pull = sorted(set(new_symbols) | set(resplit))
    gap_pull = [s for s in symbols if s not in set(full_pull)] if gap_start <= today else []

    print(f"File: {len(existing):,} rows through {last_date}; panel: {len(symbols)} symbols.")
    print(f"Gap: {gap_start} -> {today} ({len(gap_pull)} symbols).")
    print(f"Full re-pull: {len(new_symbols)} new + {len(resplit)} split symbols.")

    if not gap_pull and not full_pull:
        print("Already up to date; nothing to fetch.")
        return

    frames: list[pd.DataFrame] = [existing]
    failures: list[str] = []

    if gap_pull:
        gap_frames, gap_failures = fetch_symbols(client, gap_pull, gap_start, today, "gap")
        frames.extend(gap_frames)
        failures.extend(gap_failures)

    if full_pull:
        full_frames, full_failures = fetch_symbols(client, full_pull, window_start, today, "full")
        frames.extend(full_frames)
        failures.extend(full_failures)

    # Freshly fetched rows win over stored ones (keep="last"), so split re-pulls
    # replace stale history while a failed re-pull leaves the old rows in place.
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(["symbol", "date"], keep="last")

    combined = combined[combined["date"] >= pd.Timestamp(window_start)]
    combined = combined.sort_values(["symbol", "date"], ignore_index=True)

    added = len(combined) - len(existing)

    print(f"Writing {len(combined):,} rows ({added:+,} vs previous) to {uri} ...")
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
