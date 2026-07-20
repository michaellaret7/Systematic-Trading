"""Shared FMP statement-fetching and merge behavior for fundamentals sync jobs."""

import time

import pandas as pd
import requests

from systematic_trading.data.providers.fmp import FMPClient

RETRIES = 3
RETRY_WAIT_S = 5.0  # transient FMP errors (rate limits) clear quickly

# RuntimeError covers FMP-level errors from FMPClient; RequestException covers
# network-level failures (connection resets, timeouts) that long runs will hit.
TRANSIENT_ERRORS = (RuntimeError, requests.RequestException)

# Statement name (file prefix) -> FMPClient method that fetches it.
STATEMENT_METHODS: dict[str, str] = {
    "income": "income_statement",
    "balance": "balance_sheet",
    "cashflow": "cash_flow",
    "ratios": "ratios",
    "key_metrics": "key_metrics",
}

# Period -> row limit for an incremental refresh: enough to cover the newest
# filing plus recently restated periods, nowhere near a full-history pull.
REFRESH_LIMITS: dict[str, int] = {
    "quarter": 4,
    "annual": 2,
}


def fetch_with_retry(
    client: FMPClient, statement: str, period: str, symbol: str, limit: int
) -> pd.DataFrame:
    """One symbol's rows for one statement/period; retries transient FMP errors."""
    method = STATEMENT_METHODS[statement]

    for attempt in range(1, RETRIES + 1):
        try:
            return getattr(client, method)(symbol, period=period, limit=limit)
        except TRANSIENT_ERRORS as error:
            if attempt == RETRIES:
                raise

            print(f"  {symbol}: attempt {attempt} failed ({error}); retrying...")
            time.sleep(RETRY_WAIT_S)

    raise AssertionError("unreachable")


def fetch_recent_statements(
    client: FMPClient, statement: str, period: str, symbols: list[str]
) -> tuple[list[pd.DataFrame], list[str]]:
    """Fetch each symbol's most recent rows for one statement/period, plus failures."""
    tag = f"{statement}_{period}"
    limit = REFRESH_LIMITS[period]

    frames: list[pd.DataFrame] = []
    failures: list[str] = []

    for index, symbol in enumerate(symbols, start=1):
        try:
            frame = fetch_with_retry(client, statement, period, symbol, limit)
        except TRANSIENT_ERRORS as error:
            failures.append(symbol)
            print(f"  {symbol}: giving up ({error})")
            continue

        if not frame.empty:
            frames.append(frame)

        if index % 250 == 0:
            print(f"  [{tag}] {index}/{len(symbols)} symbols fetched...")

    return frames, failures


def merge_statement(existing: pd.DataFrame, fresh: list[pd.DataFrame]) -> pd.DataFrame:
    """Merge freshly fetched rows into a stored statement frame.

    Fresh rows win on (symbol, date), so restated periods replace their stored
    versions. The stored schema is authoritative: extra fetched columns are
    dropped and columns missing from a fetch become NaN.
    """
    # Drop extra fetched columns before the concat (its union fills missing ones
    # with NaN); reindexing frames instead would create all-NA columns, which
    # pandas concat deprecates.
    aligned = [frame[existing.columns.intersection(frame.columns)] for frame in fresh]

    combined = pd.concat([existing, *aligned], ignore_index=True)
    combined = combined.drop_duplicates(subset=["symbol", "date"], keep="last")

    combined = combined.sort_values(["symbol", "date"], ignore_index=True)

    return combined
