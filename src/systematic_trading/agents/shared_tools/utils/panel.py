"""Wide close-price matrices shared by the price-analytics agent tools.

All parquet I/O goes through ``data.repository``. Lookbacks are wall-clock —
these feed live-agent flows, never a backtest.
"""

from datetime import date

import pandas as pd

from systematic_trading.data.repository import load_daily_prices

# The parquet carries the odd half-populated date (one symbol reporting on a
# market holiday); those rows would poison any cross-sectional statistic.
MIN_UNIVERSE_OBSERVATIONS = 100


def wide_closes(start: date, symbols: list[str] | None = None) -> pd.DataFrame:
    """Date x symbol close matrix, sparse trading days dropped.

    Pass ``symbols`` for a subset; omit it for the whole stored universe.
    """
    prices = load_daily_prices(symbols=symbols, start=start, columns=["symbol", "date", "close"])

    if prices.empty:
        return pd.DataFrame()

    wide = prices.pivot_table(index="date", columns="symbol", values="close").sort_index()

    if symbols is not None:
        return wide

    return wide.loc[wide.notna().sum(axis=1) >= MIN_UNIVERSE_OBSERVATIONS]
