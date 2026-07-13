"""Agent tool: pull raw FMP fundamental statements from the S3 parquet repository.

Loads one statement (income / balance / cashflow / key_metrics / ratios) for one
ticker over a date range and returns it as YAML tabular data for the agent to
ingest. All parquet I/O goes through ``data.repository`` — this module never
builds S3 URIs or calls ``read_parquet`` itself.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal, Optional

import pandas as pd
import yaml
from agent_harness.decorator import Param, agent_tool

from systematic_trading.data.repository import load_statement, statement_columns

#     ================================
# --> Helper funcs
#     ================================


def _parse_date(value: str) -> pd.Timestamp | None:
    """Parse an ISO date string; None signals a bad input the tool reports as an error."""
    try:
        parsed = pd.Timestamp(value)
    except ValueError:
        return None

    return parsed if isinstance(parsed, pd.Timestamp) else None


def _missing_columns(requested: list[str], available: pd.Index) -> list[str]:
    """Requested column names that don't exist in the loaded statement file."""
    return [column for column in requested if column not in available]


def _frame_to_records(frame: pd.DataFrame) -> list[dict]:
    """DataFrame -> plain-python records: ISO date strings, NaN -> null, no numpy scalars."""
    frame = frame.copy()

    for column in frame.columns:
        if pd.api.types.is_datetime64_any_dtype(frame[column]):
            frame[column] = frame[column].dt.strftime("%Y-%m-%d")

    # Round-trip through JSON so numpy scalars become plain python and NaN becomes null.
    return json.loads(frame.to_json(orient="records") or "[]")


#     ================================
# --> Tool
#     ================================


@agent_tool(name="GetFundamentalStatement", safe_parallel=True)
def get_fundamental_statement(
    statement: Annotated[
        Literal["income", "balance", "cashflow", "key_metrics", "ratios"],
        Param(description="Which fundamental statement to pull."),
    ],
    ticker: Annotated[str, Param(description="Ticker symbol, e.g. 'AAPL'.")],
    start_date: Annotated[
        str, Param(description="Start of the date range (inclusive), ISO format YYYY-MM-DD.")
    ],
    end_date: Annotated[
        str, Param(description="End of the date range (inclusive), ISO format YYYY-MM-DD.")
    ],
    period: Annotated[
        Literal["quarter", "annual"],
        Param(description="Reporting cadence: 'quarter' for quarterly rows, 'annual' for yearly."),
    ] = "quarter",
    # Optional[...] not `| None`: the decorator's schema builder only unwraps
    # typing.Union, so a PEP 604 union would degrade the schema type to string.
    columns: Annotated[
        Optional[list[str]],
        Param(
            description=(
                "Optional list of column names to return, e.g. ['eps', 'epsDiluted', "
                "'incomeTaxExpense']. Omit to get every column. The 'date' column is "
                "always included. Unknown names return an error listing the valid columns."
            )
        ),
    ] = None,
) -> str:
    """
    Pull raw FMP fundamental statement data for one ticker from the S3 parquet
    repository. Returns every fiscal period whose period-end date falls inside
    [start_date, end_date] as YAML tabular data: header keys (ticker,
    statement, period) followed by a `rows` list, one mapping per fiscal
    period, oldest first. Missing values are null.

    Prefer passing `columns` to fetch only the fields you need. If you do not
    know the exact column names a statement contains, call GetStatementColumns
    first — never guess column names. Omitting `columns` returns every column
    in the file (39-64 depending on the statement), which is rarely worth the
    context. The `date` column (fiscal period end) is always included so rows
    stay anchored to their period.
    Bad inputs return an "error: ..." string; an unknown column name returns
    an error listing every valid column so you can correct it and retry.
    """
    start = _parse_date(start_date)
    end = _parse_date(end_date)

    if start is None:
        return f"error: start_date {start_date!r} is not a valid ISO date (YYYY-MM-DD)"

    if end is None:
        return f"error: end_date {end_date!r} is not a valid ISO date (YYYY-MM-DD)"

    if start > end:
        return f"error: start_date {start_date!r} is after end_date {end_date!r}"

    symbol = ticker.strip().upper()
    frame = load_statement(statement, period)

    if columns:
        missing = _missing_columns(columns, frame.columns)

        if missing:
            return (
                f"error: unknown column(s) {missing} for {statement} ({period}); "
                f"valid columns: {', '.join(frame.columns)}"
            )

    rows = frame.loc[frame["symbol"] == symbol]

    if rows.empty:
        return f"error: no {statement} ({period}) data for ticker {symbol!r}"

    rows = rows.loc[(rows["date"] >= start) & (rows["date"] <= end)]

    if rows.empty:
        return (
            f"error: no {statement} ({period}) rows for {symbol} "
            f"between {start_date} and {end_date}"
        )

    rows = rows.sort_values("date").drop(columns=["symbol"])

    if columns:
        keep = ["date"] + [column for column in columns if column not in ("date", "symbol")]
        rows = rows.loc[:, keep]

    payload = {
        "ticker": symbol,
        "statement": statement,
        "period": period,
        "rows": _frame_to_records(rows),
    }

    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)


@agent_tool(name="GetStatementColumns", safe_parallel=True)
def get_statement_columns(
    statement: Annotated[
        Literal["income", "balance", "cashflow", "key_metrics", "ratios"],
        Param(description="Which fundamental statement to list the column names for."),
    ],
) -> str:
    """
    List the exact column names available in one fundamental statement file,
    as YAML (`statement` header plus a `columns` list). Column names are
    identical for quarterly and annual data, so no period argument is needed.

    Call this before GetFundamentalStatement and pass the subset you actually
    need as its `columns` argument — pulling every field wastes context. This
    is a cheap schema-only read, so calling it once per statement type is fine.
    """
    payload = {
        "statement": statement,
        "columns": statement_columns(statement),
    }

    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)


