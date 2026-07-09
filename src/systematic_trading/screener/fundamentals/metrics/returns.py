"""Return-on-capital and profitability metrics."""

import pandas as pd

from systematic_trading.screener.fundamentals.metrics.helpers import (
    LAGS_5Y,
    rolling,
    safe_ratio,
    shift,
    span_ok,
)

TAX_RATE_CAP = 0.50


def add_returns(panel: pd.DataFrame) -> pd.DataFrame:
    """Return-on-capital and profitability metrics."""
    tax_rate = safe_ratio(panel["incomeTaxExpense_ttm"], panel["incomeBeforeTax_ttm"])
    # Loss-makers have no meaningful effective tax rate. Assume no tax benefit so
    # NOPAT keeps EBIT's sign and ROIC stays defined for them.
    tax_rate = tax_rate.clip(0.0, TAX_RATE_CAP).fillna(0.0)

    panel["nopat_ttm"] = panel["ebit_ttm"] * (1.0 - tax_rate)
    panel["invested_capital"] = (
        panel["totalDebt"] + panel["totalEquity"] - panel["cashAndShortTermInvestments"]
    )

    avg_capital = (panel["invested_capital"] + shift(panel, "invested_capital", 4)) / 2.0
    panel["roic_ttm"] = safe_ratio(panel["nopat_ttm"], avg_capital)

    floor = rolling(panel, "roic_ttm", LAGS_5Y, 16, "min")
    panel["roic_floor_5y"] = floor.where(span_ok(panel, LAGS_5Y - 1))

    # Novy-Marx gross profitability: gross profit per dollar of assets.
    avg_assets = (panel["totalAssets"] + shift(panel, "totalAssets", 4)) / 2.0
    panel["gross_profitability_ttm"] = safe_ratio(panel["grossProfit_ttm"], avg_assets)

    return panel
