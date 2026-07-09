"""Reinvestment and margin stability metrics."""

from __future__ import annotations

import pandas as pd

from systematic_trading.screeners.panels.fundamentals.constants import (
    INCREMENTAL_CAPITAL_FLOOR,
)
from systematic_trading.screeners.panels.fundamentals.metrics.helpers import (
    grouped,
    safe_ratio,
    shift,
    span_ok,
)


def add_reinvestment_metrics(df: pd.DataFrame) -> None:
    nopat_then = shift(df, "nopat_ttm", 20)
    capital_then = shift(df, "invested_capital", 20)
    capital_added = df["invested_capital"] - capital_then

    grew = capital_added > INCREMENTAL_CAPITAL_FLOOR * capital_then.abs()
    df["incremental_roic_5y"] = ((df["nopat_ttm"] - nopat_then) / capital_added).where(grew)
    df["incremental_roic_5y"] = df["incremental_roic_5y"].where(span_ok(df, 20))

    capex_out = (-df["capitalExpenditure_ttm"]).clip(lower=0)
    acquisitions_out = (-df["acquisitionsNet_ttm"]).clip(lower=0)
    df["reinvestment_rate_ttm"] = safe_ratio(
        capex_out + acquisitions_out,
        df["operatingCashFlow_ttm"],
    )

    df["gross_margin_ttm"] = safe_ratio(df["grossProfit_ttm"], df["revenue_ttm"])
    margin_std = grouped(df, "gross_margin_ttm").transform(
        lambda s: s.rolling(20, min_periods=16).std()
    )
    df["gross_margin_std_5y"] = margin_std.where(span_ok(df, 19))
