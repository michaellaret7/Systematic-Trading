"""Fail-fast DataFrame contracts for stored and computed datasets."""

from collections.abc import Collection

import pandas as pd

DAILY_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")
FUNDAMENTALS_IDENTITY_COLUMNS = ("symbol", "date", "filingDate", "sector", "industry")


def _require_columns(frame: pd.DataFrame, required: Collection[str], dataset: str) -> None:
    """Raise when a dataset is missing required columns."""
    missing = set(required) - set(frame.columns)

    if missing:
        raise ValueError(f"{dataset} is missing required columns: {sorted(missing)}")


def _require_datetime(frame: pd.DataFrame, column: str, dataset: str) -> None:
    """Raise when a required date column is not a pandas datetime dtype."""
    if not pd.api.types.is_datetime64_any_dtype(frame[column]):
        raise ValueError(f"{dataset}.{column} must have a datetime dtype")


def _require_symbols(symbols: pd.Series, dataset: str) -> None:
    """Raise when symbols are missing, blank, or not normalized strings."""
    valid = symbols.map(
        lambda value: isinstance(value, str) and bool(value) and value == value.strip().upper()
    )

    if symbols.isna().any() or not valid.all():
        raise ValueError(f"{dataset}.symbol must contain nonempty normalized strings")


def _require_unique_keys(frame: pd.DataFrame, keys: list[str], dataset: str) -> None:
    """Raise when a dataset contains duplicate key rows."""
    if frame.duplicated(keys).any():
        raise ValueError(f"{dataset} contains duplicate rows for key {keys}")


def validate_statement_frame(frame: pd.DataFrame) -> None:
    """Validate the stable identity contract shared by raw statement datasets."""
    dataset = "fundamental statement"
    _require_columns(frame, ("symbol", "date"), dataset)
    _require_symbols(frame["symbol"], dataset)
    _require_datetime(frame, "date", dataset)


def validate_fundamentals_panel(frame: pd.DataFrame) -> None:
    """Validate identity, dates, and row uniqueness for the built metrics panel."""
    dataset = "fundamentals panel"
    _require_columns(frame, FUNDAMENTALS_IDENTITY_COLUMNS, dataset)
    _require_symbols(frame["symbol"], dataset)
    _require_datetime(frame, "date", dataset)
    _require_datetime(frame, "filingDate", dataset)
    _require_unique_keys(frame, ["symbol", "date"], dataset)


def validate_daily_prices(frame: pd.DataFrame) -> None:
    """Validate the stored daily OHLCV panel contract."""
    dataset = "daily prices"
    required = ("symbol", "date", *DAILY_PRICE_COLUMNS)

    _require_columns(frame, required, dataset)
    _require_symbols(frame["symbol"], dataset)
    _require_datetime(frame, "date", dataset)
    _require_unique_keys(frame, ["symbol", "date"], dataset)

    nonnumeric = [
        column for column in DAILY_PRICE_COLUMNS if not pd.api.types.is_numeric_dtype(frame[column])
    ]

    if nonnumeric:
        raise ValueError(f"daily prices has nonnumeric OHLCV columns: {nonnumeric}")


def validate_universe(symbols: Collection[str]) -> None:
    """Validate that the active universe contains unique normalized symbols."""
    values = list(symbols)
    series = pd.Series(values, dtype="object", name="symbol")

    _require_symbols(series, "universe")

    if len(values) != len(set(values)):
        raise ValueError("universe contains duplicate symbols")
