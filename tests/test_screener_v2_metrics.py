"""Metric math for the screener fundamentals panel.

Builds a small quarterly panel with hand-computed expectations and checks the
metric groups produce exactly those numbers — including the edge cases that
matter for screening (pre-tax losses, zero denominators, filing gaps, cash
burn). No network, no S3.
"""

import numpy as np
import pandas as pd
import pytest

from systematic_trading.screener.fundamentals.metrics import compute_metrics

#     ================================
# --> Helper funcs
#     ================================

BASE_ROW = {
    "revenue": 100.0,
    "grossProfit": 60.0,
    "ebit": 20.0,
    "operatingIncome": 18.0,
    "interestExpense": 0.0,
    "incomeTaxExpense": 4.0,
    "incomeBeforeTax": 18.0,
    "netIncome": 14.0,
    "researchAndDevelopmentExpenses": 4.0,
    "weightedAverageShsOutDil": 10.0,
    "operatingCashFlow": 22.0,
    "capitalExpenditure": -8.0,
    "freeCashFlow": 14.0,
    "acquisitionsNet": 0.0,
    "stockBasedCompensation": 2.0,
    "depreciationAndAmortization": 5.0,
    "netDividendsPaid": -6.0,
    "netStockIssuance": -2.0,
    "incomeTaxesPaid": 3.0,
    "interestPaid": 0.0,
    "cashAndShortTermInvestments": 50.0,
    "goodwill": 80.0,
    "totalAssets": 400.0,
    "totalCurrentAssets": 120.0,
    "totalCurrentLiabilities": 60.0,
    "totalDebt": 100.0,
    "shortTermDebt": 20.0,
    "netDebt": 50.0,
    "totalEquity": 200.0,
    "totalLiabilities": 200.0,
    "retainedEarnings": 150.0,
    "netReceivables": 40.0,
    "inventory": 30.0,
    "accountPayables": 25.0,
    "deferredRevenue": 10.0,
    "marketCap": 1000.0,
    "enterpriseValue": 1050.0,
}

LOSS_OVERRIDES = {
    "ebit": -20.0,
    "incomeBeforeTax": -18.0,
    "incomeTaxExpense": 0.0,
    "incomeTaxesPaid": 0.0,
    "netIncome": -14.0,
    "operatingCashFlow": -22.0,
    "freeCashFlow": -14.0,
    "interestExpense": 2.0,
    "interestPaid": 2.0,
}


def make_panel() -> pd.DataFrame:
    """24 identical quarters per symbol (5y metrics need TTM history at the 20-quarter
    lag, and that TTM itself needs 4 quarters): PROF is profitable, LOSS burns cash pre-tax."""
    quarters = pd.date_range("2020-06-30", periods=24, freq="QE")
    rows = []

    for symbol, overrides in [("PROF", {}), ("LOSS", LOSS_OVERRIDES)]:
        for date in quarters:
            rows.append({"symbol": symbol, "date": date, **BASE_ROW, **overrides})

    return pd.DataFrame(rows)


def last_row(panel: pd.DataFrame, symbol: str) -> pd.Series:
    return panel[panel["symbol"] == symbol].iloc[-1]


#     ================================
# --> Tests
#     ================================


def test_ttm_needs_four_quarters():
    panel = compute_metrics(make_panel())
    prof = panel[panel["symbol"] == "PROF"].reset_index(drop=True)

    assert prof.loc[:2, "revenue_ttm"].isna().all()
    assert prof.loc[3, "revenue_ttm"] == pytest.approx(400.0)
    assert prof.loc[3, "shares_ttm"] == pytest.approx(10.0)


def test_filing_gap_voids_ttm():
    """A missing year of filings must NaN the TTM until the window is contiguous again."""
    quarters = list(pd.date_range("2020-03-31", periods=4, freq="QE")) + list(
        pd.date_range("2022-03-31", periods=4, freq="QE")
    )
    raw = pd.DataFrame([{"symbol": "GAPY", "date": date, **BASE_ROW} for date in quarters])

    panel = compute_metrics(raw).reset_index(drop=True)

    # Windows spanning the gap fail the calendar-span check; the last row is contiguous.
    assert panel.loc[4:6, "revenue_ttm"].isna().all()
    assert panel.loc[7, "revenue_ttm"] == pytest.approx(400.0)

    # The 4-quarter capital average still reaches across the gap, so ROIC stays NaN.
    assert np.isnan(panel.loc[7, "roic_ttm"])


def test_returns_metrics():
    panel = compute_metrics(make_panel())
    prof = last_row(panel, "PROF")

    # tax rate 16/72, NOPAT = 80 * (1 - 16/72); invested capital subtracts only
    # excess cash: 100 + 200 - (50 - 0.02 * 400) = 258
    expected_nopat = 80.0 * (1.0 - 16.0 / 72.0)

    assert prof["nopat_ttm"] == pytest.approx(expected_nopat)
    assert prof["invested_capital"] == pytest.approx(258.0)
    assert prof["roic_ttm"] == pytest.approx(expected_nopat / 258.0)
    assert prof["roic_floor_5y"] == pytest.approx(prof["roic_ttm"])
    assert prof["gross_profitability_ttm"] == pytest.approx(240.0 / 400.0)


def test_return_variants():
    panel = compute_metrics(make_panel())
    prof = last_row(panel, "PROF")

    expected_nopat = 80.0 * (1.0 - 16.0 / 72.0)

    # capital employed = 400 assets - 60 current liabilities
    assert prof["roce_ttm"] == pytest.approx(80.0 / 340.0)
    assert prof["croic_ttm"] == pytest.approx(56.0 / 258.0)

    # ex-goodwill capital = 258 - 80
    assert prof["roic_ex_goodwill_ttm"] == pytest.approx(expected_nopat / 178.0)

    # cash tax rate 12/72; flat company has zero trend
    assert prof["nopat_cash_ttm"] == pytest.approx(80.0 * (1.0 - 12.0 / 72.0))
    assert prof["roic_cash_tax_ttm"] == pytest.approx(80.0 * (1.0 - 12.0 / 72.0) / 258.0)
    assert prof["roic_trend_3y"] == pytest.approx(0.0)


def test_rnd_adjusted_roic():
    """Flat 4/quarter R&D: asset = 4 * sum(1..20)/20 = 42, amortization cancels the
    add-back, so only the capital base changes: 258 + 42 = 300."""
    panel = compute_metrics(make_panel())
    prof = last_row(panel, "PROF")

    expected_nopat = 80.0 * (1.0 - 16.0 / 72.0)

    assert prof["invested_capital_rnd_adj"] == pytest.approx(300.0)
    assert prof["rnd_adj_roic_ttm"] == pytest.approx(expected_nopat / 300.0)


def test_loss_maker_stays_defined():
    """Pre-tax losses fall back to a 0 tax rate so ROIC stays defined for short targets."""
    panel = compute_metrics(make_panel())
    loss = last_row(panel, "LOSS")

    assert loss["nopat_ttm"] == pytest.approx(-80.0)
    assert loss["roic_ttm"] == pytest.approx(-80.0 / 258.0)
    assert np.isnan(loss["net_debt_to_ebitda"])  # EBITDA -60 -> multiple is meaningless
    assert loss["interest_coverage"] == pytest.approx(-80.0 / 8.0)


def test_cash_quality_metrics():
    panel = compute_metrics(make_panel())
    prof = last_row(panel, "PROF")

    assert prof["fcf_margin_ttm"] == pytest.approx(56.0 / 400.0)
    assert prof["income_quality_ttm"] == pytest.approx(88.0 / 56.0)
    assert prof["fcf_positive_quarters_5y"] == pytest.approx(20.0)
    assert prof["accruals_ratio_ttm"] == pytest.approx((56.0 - 88.0) / 400.0)
    assert prof["dso_ttm"] == pytest.approx(40.0 * 365.0 / 400.0)
    assert prof["dso_change_3y"] == pytest.approx(0.0)
    assert prof["sbc_to_revenue_ttm"] == pytest.approx(8.0 / 400.0)


def test_cash_generation_metrics():
    panel = compute_metrics(make_panel())
    prof = last_row(panel, "PROF")

    assert prof["fcf_adj_ttm"] == pytest.approx(48.0)  # 56 FCF - 8 SBC
    assert prof["fcf_adj_margin_ttm"] == pytest.approx(48.0 / 400.0)
    assert prof["owner_earnings_ttm"] == pytest.approx(68.0)  # 88 OCF - min(32 capex, 20 D&A)
    assert prof["rnd_to_revenue_ttm"] == pytest.approx(16.0 / 400.0)


def test_working_capital_metrics():
    panel = compute_metrics(make_panel())
    prof = last_row(panel, "PROF")

    # COGS 160: DSO 36.5, DIO 68.4375, DPO 57.03125
    assert prof["dpo_ttm"] == pytest.approx(25.0 * 365.0 / 160.0)
    assert prof["ccc_ttm"] == pytest.approx(36.5 + 30.0 * 365.0 / 160.0 - 25.0 * 365.0 / 160.0)
    assert prof["ccc_change_3y"] == pytest.approx(0.0)


def test_balance_and_coverage():
    panel = compute_metrics(make_panel())
    prof = last_row(panel, "PROF")
    loss = last_row(panel, "LOSS")

    assert prof["ebitda_ttm"] == pytest.approx(100.0)  # 80 EBIT + 20 D&A
    assert prof["net_debt_to_ebitda"] == pytest.approx(0.5)
    assert prof["interest_coverage"] == np.inf  # no interest expense, positive EBIT

    assert prof["fcf_conversion_ttm"] == pytest.approx(0.56)
    assert prof["net_debt_to_fcf"] == pytest.approx(50.0 / 56.0)
    assert prof["st_debt_share"] == pytest.approx(0.2)
    assert prof["goodwill_to_assets"] == pytest.approx(0.2)

    # PROF pays no interest in cash; LOSS covers 8 paid from -80 pre-interest pre-tax cash.
    assert prof["cash_interest_coverage"] == np.inf
    assert loss["cash_interest_coverage"] == pytest.approx((-88.0 + 8.0 + 0.0) / 8.0)


def test_growth_flat_company():
    panel = compute_metrics(make_panel())
    prof = last_row(panel, "PROF")

    assert prof["revenue_cagr_5y"] == pytest.approx(0.0)
    assert prof["fcf_per_share_ttm"] == pytest.approx(56.0 / 10.0)
    assert prof["fcf_adj_per_share_ttm"] == pytest.approx(48.0 / 10.0)
    assert prof["fcf_adj_ps_cagr_5y"] == pytest.approx(0.0)
    assert prof["revenue_growth_years_5y"] == pytest.approx(0.0)  # flat = zero up-years
    assert prof["share_change_3y"] == pytest.approx(0.0)
    assert prof["deferred_revenue_growth_yoy"] == pytest.approx(0.0)


def test_reinvestment_and_payout():
    panel = compute_metrics(make_panel())
    prof = last_row(panel, "PROF")

    assert np.isnan(prof["incremental_roic_5y"])  # capital base never grew
    assert prof["reinvestment_rate_ttm"] == pytest.approx(32.0 / 88.0)
    assert prof["gross_margin_std_5y"] == pytest.approx(0.0)
    assert prof["operating_margin_ttm"] == pytest.approx(72.0 / 400.0)
    assert prof["operating_margin_change_3y"] == pytest.approx(0.0)
    # 20 quarters of (6 dividends + 2 buybacks) over 20 quarters of 14 FCF
    assert prof["payout_to_fcf_5y"] == pytest.approx(160.0 / 280.0)


def test_distress_metrics():
    panel = compute_metrics(make_panel())
    prof = last_row(panel, "PROF")
    loss = last_row(panel, "LOSS")

    assert prof["debt_to_assets"] == pytest.approx(0.25)
    assert prof["current_ratio"] == pytest.approx(2.0)
    assert prof["fcf_to_assets_ttm"] == pytest.approx(56.0 / 400.0)
    assert prof["debt_buildup_3y"] == pytest.approx(0.0)
    assert prof["net_debt_change_3y"] == pytest.approx(0.0)
    assert prof["dio_ttm"] == pytest.approx(30.0 * 365.0 / 160.0)

    assert np.isnan(prof["cash_runway_quarters"])  # positive FCF -> no burn
    assert loss["cash_runway_quarters"] == pytest.approx(50.0 / 14.0)  # 56 TTM burn / 4

    # Z = 1.2(60/400) + 1.4(150/400) + 3.3(80/400) + 0.6(1000/200) + 400/400
    assert prof["altman_z"] == pytest.approx(5.365)


def test_valuation_metrics():
    panel = compute_metrics(make_panel())
    prof = last_row(panel, "PROF")

    assert prof["fcf_yield_ttm"] == pytest.approx(56.0 / 1000.0)
    assert prof["fcf_adj_yield_ttm"] == pytest.approx(48.0 / 1000.0)
    assert prof["ev_to_ebitda_ttm"] == pytest.approx(10.5)
