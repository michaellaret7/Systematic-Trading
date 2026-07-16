"""DataFrame boundary contracts for stored datasets."""

import pandas as pd
import pytest

from systematic_trading.data.contracts import (
    validate_daily_prices,
    validate_fundamentals_panel,
    validate_statement_frame,
    validate_universe,
)


def daily_prices() -> pd.DataFrame:
    """One valid daily OHLCV row."""
    return pd.DataFrame(
        {
            "symbol": ["AAPL"],
            "date": pd.to_datetime(["2026-01-02"]),
            "open": [100.0],
            "high": [102.0],
            "low": [99.0],
            "close": [101.0],
            "volume": [1_000],
        }
    )


def test_valid_contracts_pass() -> None:
    """Well-formed statement, panel, price, and universe data is accepted."""
    statement = pd.DataFrame({"symbol": ["AAPL"], "date": pd.to_datetime(["2026-03-31"])})
    panel = statement.assign(
        filingDate=pd.to_datetime(["2026-05-01"]),
        sector="Technology",
        industry="Hardware",
    )

    validate_statement_frame(statement)
    validate_fundamentals_panel(panel)
    validate_daily_prices(daily_prices())
    validate_universe(["AAPL", "MSFT"])


def test_missing_required_column_fails_fast() -> None:
    """A missing storage column is reported at the boundary."""
    with pytest.raises(ValueError, match="missing required columns"):
        validate_daily_prices(daily_prices().drop(columns="close"))


def test_duplicate_panel_key_fails_fast() -> None:
    """Stored panels cannot contain duplicate symbol/date rows."""
    prices = pd.concat([daily_prices(), daily_prices()], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate rows"):
        validate_daily_prices(prices)


def test_invalid_date_dtype_fails_fast() -> None:
    """String dates are rejected instead of failing later in calculations."""
    prices = daily_prices()
    prices["date"] = prices["date"].dt.strftime("%Y-%m-%d")

    with pytest.raises(ValueError, match="datetime dtype"):
        validate_daily_prices(prices)


def test_invalid_universe_fails_fast() -> None:
    """Universe symbols must be unique and normalized."""
    with pytest.raises(ValueError, match="normalized"):
        validate_universe(["aapl"])

    with pytest.raises(ValueError, match="duplicate"):
        validate_universe(["AAPL", "AAPL"])
