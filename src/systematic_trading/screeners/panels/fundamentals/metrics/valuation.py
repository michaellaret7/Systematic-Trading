"""Valuation context metrics."""

from __future__ import annotations

import pandas as pd

from systematic_trading.screeners.panels.fundamentals.metrics.helpers import safe_ratio


def add_valuation_metrics(df: pd.DataFrame) -> None:
    # Context only: never filtered or scored by the current screens.
    df["fcf_yield_ttm"] = safe_ratio(df["freeCashFlow_ttm"], df["marketCap"])
    df["ev_to_ebitda_ttm"] = safe_ratio(df["enterpriseValue"], df["ebitda_ttm"])
