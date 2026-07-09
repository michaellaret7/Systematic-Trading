"""S3 I/O for screener: raw FMP statement parquets in, the built panel out.

This module is the only place that knows where the parquet files live. Raw
statements sit under ``fundamentals/`` (5 statements x quarter/annual); the
built panel is one shared parquet every fundamental screener reads from.
"""

import pandas as pd

from systematic_trading.config import s3_bucket

STATEMENTS = ("income", "balance", "cashflow", "key_metrics", "ratios")
PERIODS = ("quarter", "annual")
PANEL_KEY = "screeners/fundamentals_panel.parquet"


# Retrieve the S3 uri for the raw FMP statement parquet.
def statement_uri(statement: str, period: str) -> str:
    """S3 URI of one raw FMP statement parquet."""
    if statement not in STATEMENTS:
        raise ValueError(f"unknown statement {statement!r}; expected one of {STATEMENTS}")

    if period not in PERIODS:
        raise ValueError(f"unknown period {period!r}; expected one of {PERIODS}")

    return f"s3://{s3_bucket()}/fundamentals/{statement}_{period}.parquet"


# Retrieve the S3 uri for the built screener panel.
def panel_uri() -> str:
    """S3 URI of the built fundamentals panel."""
    return f"s3://{s3_bucket()}/{PANEL_KEY}"


def load_statement(
    statement: str, period: str = "quarter", columns: list[str] | None = None
) -> pd.DataFrame:
    """Load one raw statement, pulling only ``columns`` if given (parquet projection)."""
    return pd.read_parquet(statement_uri(statement, period), columns=columns)


def load_panel(columns: list[str] | None = None) -> pd.DataFrame:
    """Load the fundamentals panel; screeners pass just the columns they need."""
    return pd.read_parquet(panel_uri(), columns=columns)


def write_panel(panel: pd.DataFrame) -> None:
    """Overwrite the shared fundamentals panel on S3."""
    panel.to_parquet(panel_uri(), index=False)
