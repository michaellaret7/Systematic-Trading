"""S3 I/O for the fundamentals repository: raw FMP statements and the built panel.

This module is the only place that knows where the fundamentals parquets live.
Raw statements sit under ``fundamentals/`` (5 statements x quarter/annual); the
built panel is one shared parquet every fundamental screener reads from.
"""

import pandas as pd
import pyarrow.parquet as pq
import s3fs

from systematic_trading.config import s3_bucket
from systematic_trading.data.contracts import (
    validate_fundamentals_panel,
    validate_statement_frame,
    validate_universe,
)

STATEMENTS = ("income", "balance", "cashflow", "key_metrics", "ratios")
PERIODS = ("quarter", "annual")
PANEL_KEY = "screeners/fundamentals_panel.parquet"
UNIVERSE_KEY = "fundamentals/universe.csv"


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
    statement: str,
    period: str = "quarter",
    columns: list[str] | None = None,
    symbol: str | None = None,
) -> pd.DataFrame:
    """Load one raw statement, reading only what's asked for.

    ``columns`` projects (only those columns' bytes are fetched); ``symbol``
    pushes a filter into the read so row groups whose symbol range can't
    contain it are skipped entirely (files are sorted and row-grouped by symbol).
    """
    filters = [("symbol", "==", symbol)] if symbol else None

    return pd.read_parquet(statement_uri(statement, period), columns=columns, filters=filters)


def statement_columns(statement: str, period: str = "quarter") -> list[str]:
    """Column names of one raw statement parquet — schema-only read, no data download."""
    fs = s3fs.S3FileSystem()

    with fs.open(statement_uri(statement, period), "rb") as file:
        return pq.read_schema(file).names


# ~9 groups per file: narrow symbol ranges per group (data is symbol-sorted), so a
# one-ticker read prunes to a single group instead of downloading the whole file.
ROW_GROUP_SIZE = 20_000


def write_statement(frame: pd.DataFrame, statement: str, period: str) -> None:
    """Overwrite one raw FMP statement parquet on S3, row-grouped for pruned reads."""
    validate_statement_frame(frame)

    frame.to_parquet(statement_uri(statement, period), index=False, row_group_size=ROW_GROUP_SIZE)


def load_panel(columns: list[str] | None = None) -> pd.DataFrame:
    """Load the fundamentals panel; screeners pass just the columns they need."""
    return pd.read_parquet(panel_uri(), columns=columns)


def write_panel(panel: pd.DataFrame) -> None:
    """Overwrite the shared fundamentals panel on S3."""
    validate_fundamentals_panel(panel)

    panel.to_parquet(panel_uri(), index=False)


def load_sector_tags() -> dict[str, dict[str, str]]:
    """Symbol -> {'sector', 'industry'} tags from the fundamentals panel."""
    panel = load_panel(columns=["symbol", "sector", "industry"]).drop_duplicates("symbol")

    return {
        str(row["symbol"]): {"sector": str(row["sector"]), "industry": str(row["industry"])}
        for row in panel.to_dict("records")
    }


def panel_symbols() -> list[str]:
    """Every symbol in the fundamentals panel, alphabetical."""
    panel = load_panel(columns=["symbol"])

    return sorted(panel["symbol"].unique())


def universe_uri() -> str:
    """S3 URI of the active-universe CSV — the single source of truth for tickers."""
    return f"s3://{s3_bucket()}/{UNIVERSE_KEY}"


def load_universe() -> list[str]:
    """Symbols of the active universe, alphabetical."""
    frame = pd.read_csv(universe_uri())

    return sorted(frame["symbol"])


def write_universe(symbols: list[str]) -> None:
    """Overwrite the active-universe CSV on S3."""
    validate_universe(symbols)

    pd.DataFrame({"symbol": sorted(symbols)}).to_csv(universe_uri(), index=False)


if __name__ == "__main__":
    print(load_statement(statement="income", period="quarter", symbol="AAPL"))
