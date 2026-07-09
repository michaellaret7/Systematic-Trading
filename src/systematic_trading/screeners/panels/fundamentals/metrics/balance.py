"""Balance-sheet and coverage metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd

from systematic_trading.screeners.panels.fundamentals.metrics.helpers import safe_ratio


def add_balance_metrics(df: pd.DataFrame) -> None:
    df["ebitda_ttm"] = df["ebit_ttm"] + df["depreciationAndAmortization_ttm"]
    df["net_debt_to_ebitda"] = df["netDebt"] / df["ebitda_ttm"].where(df["ebitda_ttm"] > 0)

    coverage = safe_ratio(df["ebit_ttm"], df["interestExpense_ttm"])
    debt_free = (df["interestExpense_ttm"] <= 0) & (df["ebit_ttm"] > 0)
    df["interest_coverage"] = coverage.mask(debt_free, np.inf)
