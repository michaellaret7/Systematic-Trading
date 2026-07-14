"""Build the statement files of the S3 fundamentals repository.

Universe: FMP company screener — market cap > $2bn, price > $5, common stocks on
NASDAQ / NYSE / AMEX. For each requested period and statement type, fetch 30
years of data for every symbol and write the whole universe in one shot to
s3://<S3_BUCKET>/fundamentals/<statement>_<period>.parquet.

Usage — args are any mix of periods and statement names; omitted means all:
    uv run python scripts/push_fundamentals.py                  # everything
    uv run python scripts/push_fundamentals.py annual           # all statements, annual
    uv run python scripts/push_fundamentals.py quarter income   # one file

Full refresh: each parquet is replaced wholesale per run, so reruns are
idempotent and files never accumulate stale symbols.
"""

from __future__ import annotations

import sys
import time

import pandas as pd
import requests

from systematic_trading.data.providers.fmp import FMPClient
from systematic_trading.data.repository import load_statement, statement_uri, write_statement
from systematic_trading.data.universe import EXCLUDED_SYMBOLS

MARKET_CAP_FLOOR = 2_000_000_000
PRICE_FLOOR = 5
EXCHANGES = "NASDAQ,NYSE,AMEX"

RETRIES = 3
RETRY_WAIT_S = 5.0  # transient FMP errors (rate limits) clear quickly

# RuntimeError covers FMP-level errors from FMPClient; RequestException covers
# network-level failures (connection resets, timeouts) that long runs will hit.
TRANSIENT_ERRORS = (RuntimeError, requests.RequestException)

# Statement name (file prefix) -> FMPClient method that fetches it.
STATEMENTS: dict[str, str] = {
    "income": "income_statement",
    "balance": "balance_sheet",
    "cashflow": "cash_flow",
    "ratios": "ratios",
    "key_metrics": "key_metrics",
}

# Period (file suffix, also the FMP param) -> row limit covering 30 years.
PERIODS: dict[str, int] = {
    "quarter": 120,
    "annual": 30,
}

#     ================================
# --> Helper funcs
#     ================================


def screen_universe(client: FMPClient) -> list[str]:
    """Symbols passing the screener filters, alphabetical."""
    screened = client.screener(
        market_cap_more_than=MARKET_CAP_FLOOR,
        price_more_than=PRICE_FLOOR,
        exchange=EXCHANGES,
    )

    return sorted(set(screened["symbol"]) - EXCLUDED_SYMBOLS)


def fetch_with_retry(client: FMPClient, method: str, symbol: str, period: str) -> pd.DataFrame:
    """One symbol's rows for one statement/period; retries transient FMP errors."""
    for attempt in range(1, RETRIES + 1):
        try:
            return getattr(client, method)(symbol, period=period, limit=PERIODS[period])
        except TRANSIENT_ERRORS as error:
            if attempt == RETRIES:
                raise

            print(f"  {symbol}: attempt {attempt} failed ({error}); retrying...")
            time.sleep(RETRY_WAIT_S)

    raise AssertionError("unreachable")


def push_statement(client: FMPClient, statement: str, period: str, symbols: list[str]) -> None:
    """Fetch every symbol for one statement/period and write the file to S3."""
    method = STATEMENTS[statement]
    tag = f"{statement}_{period}"
    uri = statement_uri(statement, period)

    frames: list[pd.DataFrame] = []
    failures: list[str] = []

    for i, symbol in enumerate(symbols, start=1):
        try:
            frame = fetch_with_retry(client, method, symbol, period)
        except TRANSIENT_ERRORS as error:
            failures.append(symbol)
            print(f"  {symbol}: giving up ({error})")
            continue

        if not frame.empty:
            frames.append(frame)

        if i % 250 == 0:
            print(f"  [{tag}] {i}/{len(symbols)} symbols fetched...")

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values(["symbol", "date"], ignore_index=True)

    print(
        f"[{tag}] writing {len(combined)} rows x {combined.shape[1]} columns "
        f"for {combined['symbol'].nunique()} symbols to {uri} ..."
    )
    write_statement(combined, statement, period)

    # Read back from S3 so the round trip is verified, not assumed.
    check = load_statement(statement, period, columns=["symbol", "date"])

    print(
        f"[{tag}] read-back: {len(check)} rows, {check['symbol'].nunique()} symbols, "
        f"{check['date'].min().date()} -> {check['date'].max().date()}"
    )

    if failures:
        print(f"[{tag}] failed symbols ({len(failures)}): {', '.join(failures)}")


#     ================================
# --> Entry point
#     ================================


def main() -> None:
    args = sys.argv[1:]
    unknown = [a for a in args if a not in STATEMENTS and a not in PERIODS]

    if unknown:
        raise SystemExit(
            f"Unknown argument(s) {unknown}; choose from {list(STATEMENTS) + list(PERIODS)}."
        )

    periods = [a for a in args if a in PERIODS] or list(PERIODS)
    statements = [a for a in args if a in STATEMENTS] or list(STATEMENTS)

    client = FMPClient()
    symbols = screen_universe(client)

    print(f"Screener: {len(symbols)} symbols (mcap > $2bn, price > $5, {EXCHANGES}).")
    print(f"Pushing: {', '.join(statements)} x {', '.join(periods)}")

    for period in periods:
        for statement in statements:
            push_statement(client, statement, period, symbols)


if __name__ == "__main__":
    main()
