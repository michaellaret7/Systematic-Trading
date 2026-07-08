"""Build the Cashflow Champions screener panel in S3.

Reads the quarterly income / balance / cashflow parquets from the fundamentals
repository, computes the point-in-time metrics panel (TTM levels plus multi-year
trend and consistency statistics per symbol/quarter), and writes it wholesale to
s3://<S3_BUCKET>/screeners/cashflow_champions.parquet. Reruns are idempotent.

Usage:
    uv run python scripts/build_cashflow_champions.py

Rebuild after each `push_fundamentals.py` refresh so the panel tracks new filings.
"""

from __future__ import annotations

import pandas as pd

from systematic_trading.config import s3_bucket
from systematic_trading.screeners.csf_champions import (
    BALANCE_COLUMNS,
    CASHFLOW_COLUMNS,
    INCOME_COLUMNS,
    build_panel,
    panel_uri,
    screen,
)

STATEMENT_COLUMNS = {
    "income": INCOME_COLUMNS,
    "balance": BALANCE_COLUMNS,
    "cashflow": CASHFLOW_COLUMNS,
}


#     ================================
# --> Helper funcs
#     ================================


def load_statement(statement: str) -> pd.DataFrame:
    """One quarterly statement file from S3, metric-input columns only."""
    uri = f"s3://{s3_bucket()}/fundamentals/{statement}_quarter.parquet"

    frame = pd.read_parquet(uri, columns=STATEMENT_COLUMNS[statement])
    print(f"[{statement}] {len(frame)} rows, {frame['symbol'].nunique()} symbols")

    return frame


#     ================================
# --> Entry point
#     ================================


def main() -> None:
    income = load_statement("income")
    balance = load_statement("balance")
    cashflow = load_statement("cashflow")

    panel = build_panel(income, balance, cashflow)
    uri = panel_uri()

    print(
        f"[panel] writing {len(panel)} rows x {panel.shape[1]} columns "
        f"for {panel['symbol'].nunique()} symbols to {uri} ..."
    )
    panel.to_parquet(uri, index=False)

    # Read back from S3 so the round trip is verified, not assumed.
    check = pd.read_parquet(uri)

    print(
        f"[panel] read-back: {len(check)} rows, {check['symbol'].nunique()} symbols, "
        f"{check['date'].min().date()} -> {check['date'].max().date()}"
    )

    champions = screen(check)

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


if __name__ == "__main__":
    main()
