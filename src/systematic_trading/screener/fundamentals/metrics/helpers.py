"""Shared helpers for fundamentals metric construction.

Every metric group builds on these: per-symbol grouping, rolling windows,
lagged comparisons, and the calendar-span check that voids any window
stretched over a filing gap.
"""

import pandas as pd

TTM_WINDOW = 4  # trailing four quarters
LAGS_3Y = 12
LAGS_5Y = 20

# A window of n quarter-lags is only trusted if its calendar span is plausible.
MAX_SPAN_DAYS_PER_LAG = 98
MAX_SPAN_SLACK_DAYS = 40


def grouped(panel: pd.DataFrame, column: str):
    return panel.groupby("symbol", sort=False)[column]


def rolling(panel: pd.DataFrame, column: str, window: int, min_periods: int, op: str) -> pd.Series:
    """Per-symbol rolling aggregate (``op`` is 'sum' / 'mean' / 'min' / 'max' / 'std')."""
    return grouped(panel, column).transform(
        lambda s: getattr(s.rolling(window, min_periods=min_periods), op)()
    )


def ttm(panel: pd.DataFrame, column: str) -> pd.Series:
    return rolling(panel, column, TTM_WINDOW, TTM_WINDOW, "sum")


def shift(panel: pd.DataFrame, column: str, lags: int) -> pd.Series:
    return grouped(panel, column).shift(lags)


def span_ok(panel: pd.DataFrame, lags: int) -> pd.Series:
    """A window of n lags is only trusted if its calendar span is plausible (no filing gaps)."""
    span_days = (panel["date"] - shift(panel, "date", lags)).dt.days
    limit = lags * MAX_SPAN_DAYS_PER_LAG + MAX_SPAN_SLACK_DAYS

    return span_days <= limit


def safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Division that yields NaN wherever the denominator is not positive."""
    return numerator / denominator.where(denominator > 0)


def cagr(now: pd.Series, then: pd.Series, years: int) -> pd.Series:
    valid = (now > 0) & (then > 0)

    return ((now / then) ** (1.0 / years) - 1.0).where(valid)
