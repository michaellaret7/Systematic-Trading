"""Short-side distress metrics."""

from __future__ import annotations

import pandas as pd

from systematic_trading.screeners.panels.fundamentals.metrics.helpers import (
    grouped,
    safe_ratio,
    shift,
    span_ok,
)


def add_distress_metrics(df: pd.DataFrame) -> None:
    # Denominate in total assets wherever possible: revenue, EBITDA, and net
    # income go to zero or negative on exactly the companies a short screen targets.
    ceiling = grouped(df, "roic_ttm").transform(lambda s: s.rolling(20, min_periods=16).max())
    df["roic_ceiling_5y"] = ceiling.where(span_ok(df, 19))

    df["debt_to_assets"] = safe_ratio(df["totalDebt"], df["totalAssets"])

    avg_assets = (df["totalAssets"] + shift(df, "totalAssets", 4)) / 2.0
    df["fcf_to_assets_ttm"] = safe_ratio(df["freeCashFlow_ttm"], avg_assets)

    # Debt added over three years, scaled by the asset base it was added to.
    debt_added = df["totalDebt"] - shift(df, "totalDebt", 12)
    assets_then = shift(df, "totalAssets", 12)
    df["debt_buildup_3y"] = safe_ratio(debt_added, assets_then).where(span_ok(df, 12))

    df["current_ratio"] = safe_ratio(df["totalCurrentAssets"], df["totalCurrentLiabilities"])

    # Quarters of cash left at the TTM burn rate; NaN when TTM FCF is positive.
    burn_per_quarter = (-df["freeCashFlow_ttm"] / 4.0).where(df["freeCashFlow_ttm"] < 0)
    df["cash_runway_quarters"] = safe_ratio(df["cashAndShortTermInvestments"], burn_per_quarter)

    cogs_ttm = df["revenue_ttm"] - df["grossProfit_ttm"]
    df["dio_ttm"] = safe_ratio(df["inventory"] * 365.0, cogs_ttm)
    df["dio_change_3y"] = (df["dio_ttm"] - shift(df, "dio_ttm", 12)).where(span_ok(df, 12))
