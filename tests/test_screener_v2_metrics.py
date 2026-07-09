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
    "interestExpense": 0.0,
    "incomeTaxExpense": 4.0,
    "incomeBeforeTax": 18.0,
    "netIncome": 14.0,
    "weightedAverageShsOutDil": 10.0,
    "operatingCashFlow": 22.0,
    "capitalExpenditure": -8.0,
    "freeCashFlow": 14.0,
    "acquisitionsNet": 0.0,
    "stockBasedCompensation": 2.0,
    "depreciationAndAmortization": 5.0,
    "netDividendsPaid": -6.0,
    "netStockIssuance": -2.0,
    "cashAndShortTermInvestments": 50.0,
    "totalAssets": 400.0,
    "totalCurrentAssets": 120.0,
    "totalCurrentLiabilities": 60.0,
    "totalDebt": 100.0,
    "netDebt": 50.0,
    "totalEquity": 200.0,
    "netReceivables": 40.0,
    "inventory": 30.0,
    "marketCap": 1000.0,
    "enterpriseValue": 1050.0,
}

LOSS_OVERRIDES = {
    "ebit": -20.0,
    "incomeBeforeTax": -18.0,
    "incomeTaxExpense": 0.0,
    "netIncome": -14.0,
    "operatingCashFlow": -22.0,
    "freeCashFlow": -14.0,
    "interestExpense": 2.0,
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


def test_returns_metrics():
    panel = compute_metrics(make_panel())
    prof = last_row(panel, "PROF")

    # tax rate 16/72, NOPAT = 80 * (1 - 16/72), avg invested capital = 100 + 200 - 50
    expected_nopat = 80.0 * (1.0 - 16.0 / 72.0)

    assert prof["nopat_ttm"] == pytest.approx(expected_nopat)
    assert prof["invested_capital"] == pytest.approx(250.0)
    assert prof["roic_ttm"] == pytest.approx(expected_nopat / 250.0)
    assert prof["roic_floor_5y"] == pytest.approx(prof["roic_ttm"])
    assert prof["gross_profitability_ttm"] == pytest.approx(240.0 / 400.0)


def test_loss_maker_stays_defined():
    """Pre-tax losses fall back to a 0 tax rate so ROIC stays defined for short targets."""
    panel = compute_metrics(make_panel())
    loss = last_row(panel, "LOSS")

    assert loss["nopat_ttm"] == pytest.approx(-80.0)
    assert loss["roic_ttm"] == pytest.approx(-80.0 / 250.0)
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


def test_balance_and_coverage():
    panel = compute_metrics(make_panel())
    prof = last_row(panel, "PROF")

    assert prof["ebitda_ttm"] == pytest.approx(100.0)  # 80 EBIT + 20 D&A
    assert prof["net_debt_to_ebitda"] == pytest.approx(0.5)
    assert prof["interest_coverage"] == np.inf  # no interest expense, positive EBIT


def test_growth_flat_company():
    panel = compute_metrics(make_panel())
    prof = last_row(panel, "PROF")

    assert prof["revenue_cagr_5y"] == pytest.approx(0.0)
    assert prof["fcf_per_share_ttm"] == pytest.approx(56.0 / 10.0)
    assert prof["revenue_growth_years_5y"] == pytest.approx(0.0)  # flat = zero up-years
    assert prof["share_change_3y"] == pytest.approx(0.0)


def test_reinvestment_and_payout():
    panel = compute_metrics(make_panel())
    prof = last_row(panel, "PROF")

    assert np.isnan(prof["incremental_roic_5y"])  # capital base never grew
    assert prof["reinvestment_rate_ttm"] == pytest.approx(32.0 / 88.0)
    assert prof["gross_margin_std_5y"] == pytest.approx(0.0)
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
    assert prof["dio_ttm"] == pytest.approx(30.0 * 365.0 / 160.0)

    assert np.isnan(prof["cash_runway_quarters"])  # positive FCF -> no burn
    assert loss["cash_runway_quarters"] == pytest.approx(50.0 / 14.0)  # 56 TTM burn / 4


def test_valuation_metrics():
    panel = compute_metrics(make_panel())
    prof = last_row(panel, "PROF")

    assert prof["fcf_yield_ttm"] == pytest.approx(56.0 / 1000.0)
    assert prof["ev_to_ebitda_ttm"] == pytest.approx(10.5)
