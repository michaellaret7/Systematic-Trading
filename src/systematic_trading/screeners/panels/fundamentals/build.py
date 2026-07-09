"""Build and write the fundamentals metrics panel, then preview every screener.

Usage:
    uv run python -m systematic_trading.screeners.panels.fundamentals.build

Rerun after each `push_fundamentals.py` refresh so the panel tracks new filings.
"""

from __future__ import annotations

import pandas as pd

from systematic_trading.config import s3_bucket
from systematic_trading.data.fmp import FMPClient
from systematic_trading.screeners import SCREENERS
from systematic_trading.screeners.panels.fundamentals.constants import (
    BALANCE_COLUMNS,
    CASHFLOW_COLUMNS,
    INCOME_COLUMNS,
    KEY_METRICS_COLUMNS,
)
from systematic_trading.screeners.panels.fundamentals.panel import build_panel, panel_uri

STATEMENT_COLUMNS = {
    "income": INCOME_COLUMNS,
    "balance": BALANCE_COLUMNS,
    "cashflow": CASHFLOW_COLUMNS,
    "key_metrics": KEY_METRICS_COLUMNS,
}


def load_statement(statement: str) -> pd.DataFrame:
    """Load one quarterly fundamentals table from S3 with only needed columns."""
    uri = f"s3://{s3_bucket()}/fundamentals/{statement}_quarter.parquet"

    frame = pd.read_parquet(uri, columns=STATEMENT_COLUMNS[statement])
    print(f"[{statement}] {len(frame)} rows, {frame['symbol'].nunique()} symbols")

    return frame


def load_sectors() -> pd.DataFrame:
    """Symbol -> sector map from the FMP company screener.

    Sectors are effectively static, so today's map applied to history introduces
    no meaningful look-ahead. The floor sits below the $2bn fundamentals-universe
    cutoff so names that have shrunk since the last push keep their sector.
    """
    screened = FMPClient().screener(
        market_cap_more_than=500_000_000,
        exchange="NASDAQ,NYSE,AMEX",
        limit=10_000,
    )
    duplicate_symbols = screened["symbol"].duplicated(keep=False).sum()
    missing_sectors = screened["sector"].isna().sum()
    print(
        f"[sectors] {len(screened)} rows from company screener, "
        f"{screened['symbol'].nunique()} symbols, "
        f"{missing_sectors} missing sectors, {duplicate_symbols} duplicate-symbol rows"
    )

    return screened[["symbol", "sector"]].drop_duplicates("symbol")


def build_and_write_panel() -> pd.DataFrame:
    """Build the panel, write it to S3, verify the round trip, and return it."""
    income = load_statement("income")
    balance = load_statement("balance")
    cashflow = load_statement("cashflow")
    key_metrics = load_statement("key_metrics")

    panel = build_panel(income, balance, cashflow, key_metrics)
    panel = panel.merge(load_sectors(), on="symbol", how="left")
    missing_sector_rows = panel["sector"].isna().sum()
    if missing_sector_rows:
        print(f"[sectors] {missing_sector_rows} panel rows have no sector")

    uri = panel_uri()

    print(
        f"[panel] writing {len(panel)} rows x {panel.shape[1]} columns "
        f"for {panel['symbol'].nunique()} symbols to {uri} ..."
    )
    panel.to_parquet(uri, index=False)

    check = pd.read_parquet(uri)
    print(
        f"[panel] read-back: {len(check)} rows, {check['symbol'].nunique()} symbols, "
        f"{check['date'].min().date()} -> {check['date'].max().date()}"
    )

    return check


def print_screen_previews(panel: pd.DataFrame) -> None:
    """Preview today's passing names for every registered screener."""
    for name, screener in SCREENERS.items():
        matches = screener.screen(panel)

        print(f"\n[{name}] {len(matches)} names today:")
        print(matches[screener.PREVIEW_COLUMNS].head(30).to_string(index=False))


def main() -> None:
    """CLI entry point for rebuilding the fundamentals panel."""
    panel = build_and_write_panel()
    print_screen_previews(panel)


if __name__ == "__main__":
    main()
