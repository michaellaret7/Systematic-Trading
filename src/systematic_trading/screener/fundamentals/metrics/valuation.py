"""Valuation context metrics."""

import pandas as pd

from systematic_trading.screener.fundamentals.metrics.helpers import safe_ratio


def add_valuation(panel: pd.DataFrame) -> pd.DataFrame:
    """Valuation context metrics."""
    panel["fcf_yield_ttm"] = safe_ratio(panel["freeCashFlow_ttm"], panel["marketCap"])
    panel["ev_to_ebitda_ttm"] = safe_ratio(panel["enterpriseValue"], panel["ebitda_ttm"])

    return panel
