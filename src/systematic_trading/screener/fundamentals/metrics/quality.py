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

    # SBC is added back to OCF but dilutes owners all the same; netting it out
    # closes the loophole that flatters income quality and FCF for heavy issuers.
    panel["fcf_adj_ttm"] = panel["freeCashFlow_ttm"] - panel["stockBasedCompensation_ttm"]
    panel["fcf_adj_margin_ttm"] = safe_ratio(panel["fcf_adj_ttm"], panel["revenue_ttm"])

    # Owner earnings: OCF less maintenance capex, proxied by min(capex, D&A) —
    # growth capex is discretionary spend, not a cost of staying in business.
    capex_out_ttm = (-panel["capitalExpenditure_ttm"]).clip(lower=0)
    maintenance_capex = np.minimum(capex_out_ttm, panel["depreciationAndAmortization_ttm"])
    panel["owner_earnings_ttm"] = panel["operatingCashFlow_ttm"] - maintenance_capex

    panel["rnd_to_revenue_ttm"] = safe_ratio(
        panel["researchAndDevelopmentExpenses_ttm"], panel["revenue_ttm"]
    )

    return panel


def add_working_capital(panel: pd.DataFrame) -> pd.DataFrame:
    """Working-capital discipline: inventory, payables, and the cash conversion cycle."""
    panel["cogs_ttm"] = panel["revenue_ttm"] - panel["grossProfit_ttm"]

    panel["dio_ttm"] = safe_ratio(panel["inventory"] * 365.0, panel["cogs_ttm"])
    panel["dio_change_3y"] = (panel["dio_ttm"] - shift(panel, "dio_ttm", LAGS_3Y)).where(
        span_ok(panel, LAGS_3Y)
    )

    panel["dpo_ttm"] = safe_ratio(panel["accountPayables"] * 365.0, panel["cogs_ttm"])

    # Days of cash locked in the operating cycle; falling is discipline, rising is strain.
    panel["ccc_ttm"] = panel["dso_ttm"] + panel["dio_ttm"] - panel["dpo_ttm"]
    panel["ccc_change_3y"] = (panel["ccc_ttm"] - shift(panel, "ccc_ttm", LAGS_3Y)).where(
        span_ok(panel, LAGS_3Y)
    )

    return panel


def add_balance(panel: pd.DataFrame) -> pd.DataFrame:
    """Balance-sheet and coverage metrics."""
    panel["ebitda_ttm"] = panel["ebit_ttm"] + panel["depreciationAndAmortization_ttm"]
    panel["net_debt_to_ebitda"] = safe_ratio(panel["netDebt"], panel["ebitda_ttm"])

    coverage = safe_ratio(panel["ebit_ttm"], panel["interestExpense_ttm"])
    debt_free = (panel["interestExpense_ttm"] <= 0) & (panel["ebit_ttm"] > 0)
    panel["interest_coverage"] = coverage.mask(debt_free, np.inf)

    # Coverage on cash actually paid, immune to capitalized-interest games.
    cash_operating = (
        panel["operatingCashFlow_ttm"] + panel["interestPaid_ttm"] + panel["incomeTaxesPaid_ttm"]
    )
    cash_coverage = safe_ratio(cash_operating, panel["interestPaid_ttm"])
    cash_debt_free = (panel["interestPaid_ttm"] <= 0) & (cash_operating > 0)
    panel["cash_interest_coverage"] = cash_coverage.mask(cash_debt_free, np.inf)

    # FCF-denominated leverage is harsher than EBITDA for capex-heavy names.
    panel["fcf_conversion_ttm"] = safe_ratio(panel["freeCashFlow_ttm"], panel["ebitda_ttm"])
    panel["net_debt_to_fcf"] = safe_ratio(panel["netDebt"], panel["freeCashFlow_ttm"])

    # Share of debt due within a year: the only maturity-wall signal in our data.
    panel["st_debt_share"] = safe_ratio(panel["shortTermDebt"], panel["totalDebt"])

    panel["goodwill_to_assets"] = safe_ratio(panel["goodwill"].fillna(0.0), panel["totalAssets"])

    return panel
