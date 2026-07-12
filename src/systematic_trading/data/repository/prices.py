"""S3 I/O for the prices repository: the daily OHLCV parquet.

This module is the only place that knows where the price files live. The daily
file holds the trailing 4 years of split-adjusted OHLCV bars, one row per
``(symbol, date)``, for every symbol in the fundamentals panel.
"""

import datetime as dt

import pandas as pd

from systematic_trading.config import s3_bucket

DAILY_PRICES_KEY = "prices/daily_ohclv.parquet"


def daily_prices_uri() -> str:
    """S3 URI of the daily OHLCV parquet."""
    return f"s3://{s3_bucket()}/{DAILY_PRICES_KEY}"


def load_daily_prices(
    symbols: list[str] | None = None,
    start: dt.date | str | None = None,
    end: dt.date | str | None = None,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Load daily bars, filtered before they leave the parquet.

    ``symbols``/``start``/``end`` become parquet predicate filters, so asking
    for one ticker's history never pulls the whole universe file.
    """
    filters: list[tuple] = []

    if symbols is not None:
        filters.append(("symbol", "in", symbols))

    if start is not None:
        filters.append(("date", ">=", pd.Timestamp(start)))

    if end is not None:
        filters.append(("date", "<=", pd.Timestamp(end)))

    return pd.read_parquet(daily_prices_uri(), columns=columns, filters=filters or None)


def write_daily_prices(frame: pd.DataFrame) -> None:
    """Overwrite the daily OHLCV parquet on S3."""
    frame.to_parquet(daily_prices_uri(), index=False)
