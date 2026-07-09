"""Trailing-twelve-month flow metrics."""

from __future__ import annotations

import pandas as pd

from systematic_trading.screeners.panels.fundamentals.constants import TTM_FLOWS
from systematic_trading.screeners.panels.fundamentals.metrics.helpers import (
    grouped,
    span_ok,
    ttm,
)


def add_ttm_flows(df: pd.DataFrame) -> None:
    ttm_ok = span_ok(df, 3)

    for column in TTM_FLOWS:
        df[f"{column}_ttm"] = ttm(df, column).where(ttm_ok)

    df["shares_ttm"] = (
        grouped(df, "weightedAverageShsOutDil")
        .transform(lambda s: s.rolling(4, min_periods=4).mean())
        .where(ttm_ok)
    )
