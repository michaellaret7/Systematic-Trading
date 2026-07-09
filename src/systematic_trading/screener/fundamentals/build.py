"""Build the shared fundamentals panel.

Pulls the raw quarterly statement parquets from S3 (only the columns the
metrics need), merges them into one row per (symbol, fiscal quarter), computes
every metric group, tags each symbol with its FMP sector/industry, and writes
the result back to S3 as ``screeners/fundamentals_panel.parquet``.

The panel keeps full history plus ``filingDate`` so screeners can build
point-in-time cross-sections (``filingDate <= as_of``). Rerun any time the raw
data refreshes:

    python -m systematic_trading.screener.fundamentals.build
"""

import pandas as pd

from systematic_trading.data.fmp import FMPClient
from systematic_trading.screener.fundamentals.data import (
    load_statement,
    panel_uri,
    write_panel,
)
from systematic_trading.screener.fundamentals.metrics import compute_metrics

# Columns pulled per statement, keeping FMP's names. Only what the metrics consume.
RAW_COLUMNS: dict[str, list[str]] = {
    "income": [
        "symbol",
        "date",
        "filingDate",
        "fiscalYear",
        "period",
        "revenue",
        "grossProfit",
        "ebit",
        "interestExpense",
        "incomeBeforeTax",
        "incomeTaxExpense",
        "netIncome",
        "weightedAverageShsOutDil",
    ],
    "balance": [
        "symbol",
        "date",
        "cashAndShortTermInvestments",
        "totalAssets",
        "totalCurrentAssets",
        "totalCurrentLiabilities",
        "totalDebt",
        "netDebt",
        "totalEquity",
        "netReceivables",
        "inventory",
    ],
    "cashflow": [
        "symbol",
        "date",
        "operatingCashFlow",
        "capitalExpenditure",
        "freeCashFlow",
        "acquisitionsNet",
        "stockBasedCompensation",
        "depreciationAndAmortization",
        "netDividendsPaid",
        "netStockIssuance",
    ],
    "key_metrics": [
        "symbol",
        "date",
        "marketCap",
        "enterpriseValue",
    ],
}


def load_merged_quarters() -> pd.DataFrame:
    """Load the quarterly statements and merge them into one row per (symbol, date)."""
    merged: pd.DataFrame | None = None

    for statement, columns in RAW_COLUMNS.items():
        frame = load_statement(statement, "quarter", columns=columns)
        frame = frame.drop_duplicates(["symbol", "date"], keep="last")

        print(f"[{statement}] {len(frame):,} rows, {frame['symbol'].nunique():,} symbols")

        if merged is None:
            merged = frame
        else:
            merged = merged.merge(frame, on=["symbol", "date"], how="left")

    merged["date"] = pd.to_datetime(merged["date"])
    merged["filingDate"] = pd.to_datetime(merged["filingDate"])

    return merged


def load_sectors() -> pd.DataFrame:
    """This appends the sectors to the screener panel"""
    universe = FMPClient().screener(limit=10_000)

    return universe[["symbol", "sector", "industry"]].drop_duplicates("symbol")


def main() -> None:
    """Build the panel end to end and write it to S3."""
    merged = load_merged_quarters()

    panel = compute_metrics(merged)
    panel = panel.merge(load_sectors(), on="symbol", how="left")

    write_panel(panel)
    print(panel.head(10))

    print(
        f"[panel] {len(panel):,} rows, {panel['symbol'].nunique():,} symbols, "
        f"{len(panel.columns)} columns -> {panel_uri()}"
    )


if __name__ == "__main__":
    main()
