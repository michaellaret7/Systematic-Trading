"""Build the Cashflow Champions point-in-time metrics panel."""

from __future__ import annotations

import pandas as pd

from systematic_trading.screeners.csf_champions.constants import (
    BALANCE_COLUMNS,
    CASHFLOW_COLUMNS,
    INCOME_COLUMNS,
)
from systematic_trading.screeners.csf_champions.metrics import add_metrics

STATEMENT_COLUMNS = {
    "income": INCOME_COLUMNS,
    "balance": BALANCE_COLUMNS,
    "cashflow": CASHFLOW_COLUMNS,
}


def build_panel(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    cashflow: pd.DataFrame,
) -> pd.DataFrame:
    """Compute one look-ahead-safe metrics row per symbol and fiscal quarter."""
    statements = {
        "income": income[INCOME_COLUMNS],
        "balance": balance[BALANCE_COLUMNS],
        "cashflow": cashflow[CASHFLOW_COLUMNS],
    }

    df = _join_statements(statements)
    df = df.sort_values(["symbol", "date"], ignore_index=True)

    add_metrics(df)

    input_columns = set().union(*STATEMENT_COLUMNS.values())
    metric_columns = [column for column in df.columns if column not in input_columns]

    return df[["symbol", "date", *metric_columns]]


def _join_statements(statements: dict[str, pd.DataFrame]) -> pd.DataFrame:
    df: pd.DataFrame | None = None

    for name, statement in statements.items():
        statement = statement.rename(columns={"acceptedDate": f"accepted_{name}"})
        df = statement if df is None else df.merge(statement, on=["symbol", "date"], how="inner")

    if df is None:
        raise ValueError("at least one statement is required")

    accepted_columns = ["accepted_income", "accepted_balance", "accepted_cashflow"]
    df["available_from"] = df[accepted_columns].max(axis=1)

    return df.drop(columns=accepted_columns)
