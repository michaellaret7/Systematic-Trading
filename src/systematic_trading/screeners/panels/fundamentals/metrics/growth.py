"""Growth and dilution metrics."""

from __future__ import annotations

import pandas as pd

from systematic_trading.screeners.panels.fundamentals.metrics.helpers import (
    cagr,
    grouped,
    safe_ratio,
    shift,
    span_ok,
)


def add_growth_metrics(df: pd.DataFrame) -> None:
    ok_5y = span_ok(df, 20)

    revenue_then = shift(df, "revenue_ttm", 20)
    df["revenue_cagr_5y"] = cagr(df["revenue_ttm"], revenue_then, 5).where(ok_5y)

    df["fcf_per_share_ttm"] = safe_ratio(df["freeCashFlow_ttm"], df["shares_ttm"])
    fcf_ps_then = shift(df, "fcf_per_share_ttm", 20)
    df["fcf_ps_cagr_5y"] = cagr(df["fcf_per_share_ttm"], fcf_ps_then, 5).where(ok_5y)

    yoy_positive = (df["revenue_ttm"] > shift(df, "revenue_ttm", 4)).astype(float)
    yoy_positive = yoy_positive.where(shift(df, "revenue_ttm", 4).notna())

    flags = df.assign(yoy=yoy_positive)
    lagged = [grouped(flags, "yoy").shift(lag) for lag in (0, 4, 8, 12, 16)]
    df["revenue_growth_years_5y"] = pd.concat(lagged, axis=1).sum(axis=1, skipna=False)
    df["revenue_growth_years_5y"] = df["revenue_growth_years_5y"].where(ok_5y)

    shares_then = shift(df, "shares_ttm", 12)
    df["share_change_3y"] = (df["shares_ttm"] / shares_then - 1.0).where(span_ok(df, 12))
