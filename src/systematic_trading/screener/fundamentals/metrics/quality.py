"""Cash quality, accounting quality, and balance-sheet strength metrics."""

import numpy as np
import pandas as pd

from systematic_trading.screener.fundamentals.metrics.helpers import (
    LAGS_3Y,
    LAGS_5Y,
    avg_4q,
    safe_ratio,
    shift,
    span_ok,
)


def add_cash_quality(panel: pd.DataFrame) -> pd.DataFrame:
    """Cash quality and accounting quality metrics."""
    panel["fcf_margin_ttm"] = safe_ratio(panel["freeCashFlow_ttm"], panel["revenue_ttm"])
    panel["income_quality_ttm"] = safe_ratio(panel["operatingCashFlow_ttm"], panel["netIncome_ttm"])

    positive_fcf = (panel["freeCashFlow"] > 0).astype(float)
    streak = positive_fcf.groupby(panel["symbol"], sort=False).transform(
        lambda s: s.rolling(LAGS_5Y, min_periods=LAGS_5Y).sum()
    )
    panel["fcf_positive_quarters_5y"] = streak.where(span_ok(panel, LAGS_5Y - 1))

    avg_assets = avg_4q(panel, "totalAssets")
    accruals = panel["netIncome_ttm"] - panel["operatingCashFlow_ttm"]
    panel["accruals_ratio_ttm"] = safe_ratio(accruals, avg_assets)

    panel["dso_ttm"] = safe_ratio(panel["netReceivables"] * 365.0, panel["revenue_ttm"])
    panel["dso_change_3y"] = (panel["dso_ttm"] - shift(panel, "dso_ttm", LAGS_3Y)).where(
        span_ok(panel, LAGS_3Y)
    )
    panel["sbc_to_revenue_ttm"] = safe_ratio(
        panel["stockBasedCompensation_ttm"], panel["revenue_ttm"]
    )

    return panel


def add_balance(panel: pd.DataFrame) -> pd.DataFrame:
    """Balance-sheet and coverage metrics."""
    panel["ebitda_ttm"] = panel["ebit_ttm"] + panel["depreciationAndAmortization_ttm"]
    panel["net_debt_to_ebitda"] = safe_ratio(panel["netDebt"], panel["ebitda_ttm"])

    coverage = safe_ratio(panel["ebit_ttm"], panel["interestExpense_ttm"])
    debt_free = (panel["interestExpense_ttm"] <= 0) & (panel["ebit_ttm"] > 0)
    panel["interest_coverage"] = coverage.mask(debt_free, np.inf)

    return panel
