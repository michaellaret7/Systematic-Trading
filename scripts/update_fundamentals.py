"""Incrementally update the statement files of the S3 fundamentals repository.

Companies file new fundamentals every quarter; this job pulls only what is new
instead of rebuilding 30 years of history like push_fundamentals.py:

- Watermark: the max ``acceptedDate`` in the stored income/quarter file — the
  most recent filing already held.
- Candidates: universe symbols with an earnings announcement between shortly
  before the watermark and today (FMP earnings calendar). The pad covers the
  lag between a press release and its SEC filing landing.
- Merge: each candidate's recent rows (4 quarters / 2 annual) are merged into
  every statement parquet; fresh rows win on (symbol, date), so restated
  periods are replaced too.

The universe itself never changes here — adding or dropping symbols (and
backfilling anything this job missed) stays push_fundamentals.py's job. When
new rows land, the shared screener panel is rebuilt so downstream screeners
see them. Rerunning on an up-to-date file is a cheap no-op.

Usage:
    uv run python scripts/update_fundamentals.py
"""

from __future__ import annotations

import datetime as dt

from systematic_trading.data.fundamentals_sync import fetch_recent_statements, merge_statement
from systematic_trading.data.providers.fmp import FMPClient
from systematic_trading.data.repository import load_statement, load_universe, write_statement
from systematic_trading.data.repository.fundamentals import PERIODS, STATEMENTS
from systematic_trading.screener.fundamentals.build import build_panel

# Announcements precede their SEC filing by up to a few weeks, so the calendar
# window starts this far before the watermark to catch filings accepted just
# after it. Over-fetching is harmless — the merge is idempotent.
LOOKBACK_DAYS = 30

#     ================================
# --> Helper funcs
#     ================================


def update_statement(client: FMPClient, statement: str, period: str, symbols: list[str]) -> None:
    """Merge one statement/period's fresh rows into its S3 parquet and verify."""
    tag = f"{statement}_{period}"
    existing = load_statement(statement, period)

    fresh, failures = fetch_recent_statements(client, statement, period, symbols)
    merged = merge_statement(existing, fresh)

    added = len(merged) - len(existing)

    print(f"[{tag}] writing {len(merged):,} rows ({added:+,} vs previous) ...")
    write_statement(merged, statement, period)

    # Read back from S3 so the round trip is verified, not assumed.
    check = load_statement(statement, period, columns=["symbol", "date"])

    print(
        f"[{tag}] read-back: {len(check):,} rows, {check['symbol'].nunique():,} symbols, "
        f"{check['date'].min().date()} -> {check['date'].max().date()}"
    )

    if failures:
        print(f"[{tag}] failed symbols ({len(failures)}): {', '.join(failures)}")


#     ================================
# --> Entry point
#     ================================


def main() -> None:
    client = FMPClient()
    universe = set(load_universe())

    accepted = load_statement("income", "quarter", columns=["acceptedDate"])["acceptedDate"]
    watermark = accepted.max().date()

    today = dt.date.today()
    window_start = watermark - dt.timedelta(days=LOOKBACK_DAYS)

    announced = client.earnings_calendar(window_start, today)
    candidates = sorted(set(announced["symbol"]) & universe)

    print(f"Universe: {len(universe)} symbols; last stored filing accepted {watermark}.")
    print(f"Earnings {window_start} -> {today}: {len(candidates)} universe symbols announced.")

    if not candidates:
        print("No new filings; nothing to fetch.")
        return

    for period in PERIODS:
        for statement in STATEMENTS:
            update_statement(client, statement, period, candidates)

    # Screeners read the built panel, not the raw files — rebuild it last so the screener has the latest data
    build_panel()


if __name__ == "__main__":
    main()
