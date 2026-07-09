"""Cash quality and accounting quality metrics."""

from __future__ import annotations

import pandas as pd

from systematic_trading.screeners.panels.fundamentals.metrics.helpers import (
    grouped,
    safe_ratio,
    shift,
    span_ok,
)


def add_cash_quality_metrics(df: pd.DataFrame) -> None:
    df["fcf_margin_ttm"] = safe_ratio(df["freeCashFlow_ttm"], df["revenue_ttm"])
    df["income_quality_ttm"] = safe_ratio(df["operatingCashFlow_ttm"], df["netIncome_ttm"])

    positive_fcf = (df["freeCashFlow"] > 0).astype(float)
    streak = grouped(df.assign(fcf_pos=positive_fcf), "fcf_pos").transform(
        lambda s: s.rolling(20, min_periods=20).sum()
    )
    df["fcf_positive_quarters_5y"] = streak.where(span_ok(df, 19))

    avg_assets = (df["totalAssets"] + shift(df, "totalAssets", 4)) / 2.0
    accruals = df["netIncome_ttm"] - df["operatingCashFlow_ttm"]
    df["accruals_ratio_ttm"] = safe_ratio(accruals, avg_assets)

    df["dso_ttm"] = safe_ratio(df["netReceivables"] * 365.0, df["revenue_ttm"])
    df["dso_change_3y"] = (df["dso_ttm"] - shift(df, "dso_ttm", 12)).where(span_ok(df, 12))
    df["sbc_to_revenue_ttm"] = safe_ratio(df["stockBasedCompensation_ttm"], df["revenue_ttm"])
