"""Build and write the Cashflow Champions screener panel."""

from __future__ import annotations

import pandas as pd

from systematic_trading.config import s3_bucket
from systematic_trading.screeners.csf_champions.constants import (
    BALANCE_COLUMNS,
    CASHFLOW_COLUMNS,
    INCOME_COLUMNS,
    KEY_METRICS_COLUMNS,
)
from systematic_trading.screeners.csf_champions.panel import build_panel
from systematic_trading.screeners.csf_champions.screen import panel_uri, screen

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


def build_and_write_panel() -> pd.DataFrame:
    """Build the panel, write it to S3, verify the round trip, and return it."""
    income = load_statement("income")
    balance = load_statement("balance")
    cashflow = load_statement("cashflow")
    key_metrics = load_statement("key_metrics")

    panel = build_panel(income, balance, cashflow, key_metrics)
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


def print_current_champions(panel: pd.DataFrame) -> None:
    """Print a compact preview of today's passing names."""
    champions = screen(panel)

    print(f"\nCashflow Champions today ({len(champions)} names):")
    print(
        champions[
            [
                "symbol",
                "score",
                "roic_ttm",
                "fcf_margin_ttm",
                "revenue_cagr_5y",
                "net_debt_to_ebitda",
                "fcf_ps_cagr_5y",
            ]
        ]
        .head(30)
        .to_string(index=False)
    )


def main() -> None:
    """CLI entry point for rebuilding the Cashflow Champions panel."""
    panel = build_and_write_panel()
    print_current_champions(panel)


if __name__ == "__main__":
    main()
