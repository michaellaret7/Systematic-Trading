"""Return-on-capital and profitability metrics."""

from __future__ import annotations

import pandas as pd

from systematic_trading.screeners.panels.fundamentals.constants import TAX_RATE_CAP
from systematic_trading.screeners.panels.fundamentals.metrics.helpers import (
    grouped,
    safe_ratio,
    shift,
    span_ok,
)


def add_returns_metrics(df: pd.DataFrame) -> None:
    tax_rate = safe_ratio(df["incomeTaxExpense_ttm"], df["incomeBeforeTax_ttm"])
    # Loss-makers have no meaningful effective tax rate. Assume no tax benefit so
    # NOPAT keeps EBIT's sign and ROIC stays defined for them.
    tax_rate = tax_rate.clip(0.0, TAX_RATE_CAP).fillna(0.0)

    df["nopat_ttm"] = df["ebit_ttm"] * (1.0 - tax_rate)
    df["invested_capital"] = df["totalDebt"] + df["totalEquity"] - df["cashAndShortTermInvestments"]

    avg_capital = (df["invested_capital"] + shift(df, "invested_capital", 4)) / 2.0
    df["roic_ttm"] = safe_ratio(df["nopat_ttm"], avg_capital)

    floor = grouped(df, "roic_ttm").transform(lambda s: s.rolling(20, min_periods=16).min())
    df["roic_floor_5y"] = floor.where(span_ok(df, 19))

    # Novy-Marx gross profitability: gross profit per dollar of assets.
    avg_assets = (df["totalAssets"] + shift(df, "totalAssets", 4)) / 2.0
    df["gross_profitability_ttm"] = safe_ratio(df["grossProfit_ttm"], avg_assets)
