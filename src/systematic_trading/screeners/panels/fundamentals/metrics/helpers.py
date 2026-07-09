"""Shared helpers for fundamentals metric construction."""

from __future__ import annotations

import pandas as pd
from pandas.api.typing import SeriesGroupBy

from systematic_trading.screeners.panels.fundamentals.constants import (
    MAX_SPAN_DAYS_PER_LAG,
    MAX_SPAN_SLACK_DAYS,
)


def grouped(df: pd.DataFrame, column: str) -> SeriesGroupBy:
    return df.groupby("symbol", sort=False)[column]


def ttm(df: pd.DataFrame, column: str) -> pd.Series:
    return grouped(df, column).transform(lambda s: s.rolling(4, min_periods=4).sum())


def shift(df: pd.DataFrame, column: str, lags: int) -> pd.Series:
    return grouped(df, column).shift(lags)


def span_ok(df: pd.DataFrame, lags: int) -> pd.Series:
    span_days = (df["date"] - shift(df, "date", lags)).dt.days
    limit = lags * MAX_SPAN_DAYS_PER_LAG + MAX_SPAN_SLACK_DAYS

    return span_days <= limit


def safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.where(denominator > 0)


def cagr(now: pd.Series, then: pd.Series, years: int) -> pd.Series:
    valid = (now > 0) & (then > 0)

    return ((now / then) ** (1.0 / years) - 1.0).where(valid)
