"""Return-on-capital and profitability metrics."""

import pandas as pd

from systematic_trading.screener.fundamentals.metrics.helpers import (
    LAGS_5Y,
    avg_4q,
    rolling,
    safe_ratio,
    span_ok,
)

TAX_RATE_CAP = 0.50
OPERATING_CASH_PCT_OF_REVENUE = 0.02

def add_returns(panel: pd.DataFrame) -> pd.DataFrame:
    """Return-on-capital and profitability metrics."""
    tax_rate = safe_ratio(panel["incomeTaxExpense_ttm"], panel["incomeBeforeTax_ttm"])
    # Loss-makers have no meaningful effective tax rate. Assume no tax benefit so
    # NOPAT keeps EBIT's sign and ROIC stays defined for them.
    tax_rate = tax_rate.clip(0.0, TAX_RATE_CAP).fillna(0.0)

    panel["nopat_ttm"] = panel["ebit_ttm"] * (1.0 - tax_rate)

    # Subtract only cash beyond an operating allowance (2% of TTM revenue): removing
    # all cash inflates ROIC for cash-rich names and can push capital negative
    # (NaN ROIC) for exactly the companies a quality screen wants.
    excess_cash = (panel["cashAndShortTermInvestments"] - OPERATING_CASH_PCT_OF_REVENUE * panel["revenue_ttm"]).clip(lower=0.0)

    panel["invested_capital"] = panel["totalDebt"] + panel["totalEquity"] - excess_cash

    avg_capital = avg_4q(panel, "invested_capital")
    panel["roic_ttm"] = safe_ratio(panel["nopat_ttm"], avg_capital)

    floor = rolling(panel, "roic_ttm", LAGS_5Y, 16, "min")
    panel["roic_floor_5y"] = floor.where(span_ok(panel, LAGS_5Y - 1))

    # Novy-Marx gross profitability: gross profit per dollar of assets.
    avg_assets = avg_4q(panel, "totalAssets")
    panel["gross_profitability_ttm"] = safe_ratio(panel["grossProfit_ttm"], avg_assets)

    return panel
