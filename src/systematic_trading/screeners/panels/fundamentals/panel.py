"""Build, locate, and load the fundamentals point-in-time metrics panel."""

from __future__ import annotations

import pandas as pd

from systematic_trading.config import s3_bucket
from systematic_trading.screeners.panels.fundamentals.constants import (
    BALANCE_COLUMNS,
    CASHFLOW_COLUMNS,
    INCOME_COLUMNS,
    KEY_METRICS_COLUMNS,
    PANEL_KEY,
)
from systematic_trading.screeners.panels.fundamentals.metrics import add_metrics
from systematic_trading.screeners.shared.validation import require_columns, require_unique_keys

STATEMENT_COLUMNS = {
    "income": INCOME_COLUMNS,
    "balance": BALANCE_COLUMNS,
    "cashflow": CASHFLOW_COLUMNS,
}


def panel_uri() -> str:
    """S3 location of the built fundamentals metrics panel."""
    return f"s3://{s3_bucket()}/{PANEL_KEY}"


def load_panel() -> pd.DataFrame:
    """Read the full fundamentals metrics panel from S3 (shared by all screeners)."""
    return pd.read_parquet(panel_uri())


def build_panel(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    cashflow: pd.DataFrame,
    key_metrics: pd.DataFrame,
) -> pd.DataFrame:
    """Compute one look-ahead-safe metrics row per symbol and fiscal quarter.

    The three statements are joined inner (a quarter needs all of them); key
    metrics joins left, so quarters it doesn't cover just carry NaN valuations.
    """
    _validate_inputs(income, balance, cashflow, key_metrics)

    statements = {
        "income": income[INCOME_COLUMNS],
        "balance": balance[BALANCE_COLUMNS],
        "cashflow": cashflow[CASHFLOW_COLUMNS],
    }

    df = _join_statements(statements)
    df = df.merge(
        key_metrics[KEY_METRICS_COLUMNS],
        on=["symbol", "date"],
        how="left",
        validate="one_to_one",
    )
    df = df.sort_values(["symbol", "date"], ignore_index=True)

    add_metrics(df)

    input_columns = set().union(*STATEMENT_COLUMNS.values())
    metric_columns = [column for column in df.columns if column not in input_columns]

    return df[["symbol", "date", *metric_columns]]


def _validate_inputs(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    cashflow: pd.DataFrame,
    key_metrics: pd.DataFrame,
) -> None:
    inputs = {
        "income statement": (income, INCOME_COLUMNS),
        "balance sheet": (balance, BALANCE_COLUMNS),
        "cashflow statement": (cashflow, CASHFLOW_COLUMNS),
        "key metrics": (key_metrics, KEY_METRICS_COLUMNS),
    }

    for context, (frame, columns) in inputs.items():
        require_columns(frame, columns, context)
        require_unique_keys(frame, ["symbol", "date"], context)


def _join_statements(statements: dict[str, pd.DataFrame]) -> pd.DataFrame:
    df: pd.DataFrame | None = None

    for name, statement in statements.items():
        statement = statement.rename(columns={"acceptedDate": f"accepted_{name}"})
        df = (
            statement
            if df is None
            else df.merge(statement, on=["symbol", "date"], how="inner", validate="one_to_one")
        )

    if df is None:
        raise ValueError("at least one statement is required")

    accepted_columns = ["accepted_income", "accepted_balance", "accepted_cashflow"]
    df["available_from"] = df[accepted_columns].max(axis=1)

    return df.drop(columns=accepted_columns)
