"""Trailing-twelve-month flow metrics — the building blocks every other group consumes."""

import pandas as pd

from systematic_trading.screener.fundamentals.metrics.helpers import (
    TTM_WINDOW,
    rolling,
    span_ok,
    ttm,
)

FLOW_COLUMNS = [
    "revenue",
    "grossProfit",
    "ebit",
    "operatingIncome",
    "interestExpense",
    "incomeTaxExpense",
    "incomeBeforeTax",
    "netIncome",
    "researchAndDevelopmentExpenses",
    "operatingCashFlow",
    "capitalExpenditure",
    "freeCashFlow",
    "acquisitionsNet",
    "stockBasedCompensation",
    "depreciationAndAmortization",
    "incomeTaxesPaid",
    "interestPaid",
]


def add_ttm_flows(panel: pd.DataFrame) -> pd.DataFrame:
    """Trailing-twelve-month sums of all flow columns, plus average diluted shares."""
    ttm_ok = span_ok(panel, TTM_WINDOW - 1)

    for column in FLOW_COLUMNS:
        panel[f"{column}_ttm"] = ttm(panel, column).where(ttm_ok)

    panel["shares_ttm"] = rolling(
        panel, "weightedAverageShsOutDil", TTM_WINDOW, TTM_WINDOW, "mean"
    ).where(ttm_ok)

    return panel
