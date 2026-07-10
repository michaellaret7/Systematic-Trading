"""Return-on-capital and profitability metrics."""

import numpy as np
import pandas as pd

from systematic_trading.screener.fundamentals.metrics.helpers import (
    LAGS_3Y,
    LAGS_5Y,
    avg_4q,
    rolling,
    safe_ratio,
    shift,
    span_ok,
)

TAX_RATE_CAP = 0.50
OPERATING_CASH_PCT_OF_REVENUE = 0.02
RND_AMORT_YEARS = 5


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
    excess_cash = (
        panel["cashAndShortTermInvestments"] - OPERATING_CASH_PCT_OF_REVENUE * panel["revenue_ttm"]
    ).clip(lower=0.0)

    panel["invested_capital"] = panel["totalDebt"] + panel["totalEquity"] - excess_cash

    avg_capital = avg_4q(panel, "invested_capital")
    panel["roic_ttm"] = safe_ratio(panel["nopat_ttm"], avg_capital)

    floor = rolling(panel, "roic_ttm", LAGS_5Y, 16, "min")
    panel["roic_floor_5y"] = floor.where(span_ok(panel, LAGS_5Y - 1))

    # Novy-Marx gross profitability: gross profit per dollar of assets.
    avg_assets = avg_4q(panel, "totalAssets")
    panel["gross_profitability_ttm"] = safe_ratio(panel["grossProfit_ttm"], avg_assets)

    return panel


def add_return_variants(panel: pd.DataFrame) -> pd.DataFrame:
    """Alternative return-on-capital lenses: ROCE, cash returns, goodwill, cash taxes, trend."""
    avg_capital = avg_4q(panel, "invested_capital")

    # Classic ROCE (Terry Smith's metric): operating profit on total capital
    # employed; stays meaningful when buybacks distort equity.
    panel["capital_employed"] = panel["totalAssets"] - panel["totalCurrentLiabilities"]
    panel["roce_ttm"] = safe_ratio(panel["ebit_ttm"], avg_4q(panel, "capital_employed"))

    # CROIC: cash generated per dollar of invested capital ("return on capital. In cash.")
    panel["croic_ttm"] = safe_ratio(panel["freeCashFlow_ttm"], avg_capital)

    # Ex-goodwill ROIC shows the underlying business's reinvestment economics;
    # the with-goodwill column judges management's full M&A record.
    panel["invested_capital_ex_goodwill"] = panel["invested_capital"] - panel["goodwill"].fillna(
        0.0
    )
    panel["roic_ex_goodwill_ttm"] = safe_ratio(
        panel["nopat_ttm"], avg_4q(panel, "invested_capital_ex_goodwill")
    )

    # NOPAT on taxes actually paid, immune to provision/deferred-tax games.
    # Same loss-maker fallback as the accrual tax rate.
    cash_tax_rate = safe_ratio(panel["incomeTaxesPaid_ttm"], panel["incomeBeforeTax_ttm"])
    cash_tax_rate = cash_tax_rate.clip(0.0, TAX_RATE_CAP).fillna(0.0)

    panel["nopat_cash_ttm"] = panel["ebit_ttm"] * (1.0 - cash_tax_rate)
    panel["roic_cash_tax_ttm"] = safe_ratio(panel["nopat_cash_ttm"], avg_capital)

    # ROIC migration carries return information beyond the level (Mauboussin).
    panel["roic_trend_3y"] = (panel["roic_ttm"] - shift(panel, "roic_ttm", LAGS_3Y)).where(
        span_ok(panel, LAGS_3Y)
    )

    return panel


def add_rnd_adjusted_returns(panel: pd.DataFrame) -> pd.DataFrame:
    """ROIC with R&D capitalized over five years instead of expensed.

    Expensing R&D understates capital and overstates returns for research-heavy
    names (Apple FY2022: ~162% traditional vs ~70% adjusted); this variant puts
    them on the same footing as capex-heavy businesses.
    """
    lags = RND_AMORT_YEARS * 4
    rnd = panel["researchAndDevelopmentExpenses"].fillna(0.0)
    by_symbol = rnd.groupby(panel["symbol"], sort=False)

    # Straight-line amortization: the quarter spent k quarters ago retains
    # (lags - k) / lags of its value in the R&D asset.
    shifted = pd.concat([by_symbol.shift(k) for k in range(lags)], axis=1)
    weights = np.array([(lags - k) / lags for k in range(lags)])

    rnd_asset = (shifted * weights).sum(axis=1, skipna=False)
    rnd_amort_ttm = shifted.sum(axis=1, skipna=False) / RND_AMORT_YEARS

    # Add back the expense, charge the amortization (pre-tax approximation, per
    # Damodaran), and carry the unamortized spend as capital.
    nopat_adj = panel["nopat_ttm"] + panel["researchAndDevelopmentExpenses_ttm"] - rnd_amort_ttm
    capital_adj = panel["invested_capital"] + rnd_asset

    panel["invested_capital_rnd_adj"] = capital_adj.where(span_ok(panel, lags - 1))
    panel["rnd_adj_roic_ttm"] = safe_ratio(nopat_adj, avg_4q(panel, "invested_capital_rnd_adj"))

    return panel
