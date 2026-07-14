"""Cashflow Champions quality-at-a-reasonable-price policy."""

import numpy as np
import pandas as pd

from systematic_trading.screener.fundamentals.screeners import champions


def make_panel() -> pd.DataFrame:
    symbols = ["CHEAP", "EXPENSIVE", "INCOMPLETE"]
    frame = pd.DataFrame(
        {
            "symbol": symbols,
            "date": pd.to_datetime(["2026-03-31"] * 3),
            "filingDate": pd.to_datetime(["2026-05-01"] * 3),
            "sector": ["Technology"] * 3,
            "industry": ["Software"] * 3,
        }
    )

    passing_values = {
        "roic_ttm": 0.20,
        "roic_floor_5y": 0.15,
        "fcf_margin_ttm": 0.10,
        "fcf_adj_margin_ttm": 0.08,
        "income_quality_ttm": 1.2,
        "fcf_positive_quarters_5y": 20,
        "accruals_ratio_ttm": 0.01,
        "dso_change_3y": 0.0,
        "sbc_to_revenue_ttm": 0.02,
        "net_debt_to_ebitda": 0.5,
        "interest_coverage": 20.0,
        "revenue_cagr_5y": 0.10,
        "revenue_growth_years_5y": 5,
        "fcf_ps_cagr_5y": 0.10,
        "share_change_3y": 0.0,
        "incremental_roic_5y": 0.20,
        "gross_profitability_ttm": 0.50,
        "payout_to_fcf_5y": 0.50,
        "gross_margin_std_5y": 0.02,
    }
    for column, value in passing_values.items():
        frame[column] = value

    frame["fcf_yield_ttm"] = [0.06, 0.025, 0.05]
    frame["fcf_adj_yield_ttm"] = [0.05, 0.02, np.nan]
    frame["earnings_yield_ttm"] = [0.04, 0.02, 0.04]
    frame["owner_earnings_yield_ttm"] = [0.06, 0.025, 0.06]
    frame["ev_to_ebitda_ttm"] = [15.0, 35.0, 15.0]

    for column in champions.CONTEXT_COLUMNS:
        if column not in frame:
            frame[column] = 1.0

    return frame


def test_champions_returns_full_universe_without_gate_flags(monkeypatch):
    panel = make_panel()
    monkeypatch.setattr(champions, "load_panel", lambda columns: panel[columns].copy())

    result = champions.screen(as_of="2026-06-01")

    assert result["symbol"].tolist() == ["CHEAP", "EXPENSIVE", "INCOMPLETE"]
    assert {
        "passes_quality",
        "has_complete_valuation",
        "extreme_valuation",
        "eligible",
    }.isdisjoint(result.columns)
    assert np.isnan(result.set_index("symbol").loc["INCOMPLETE", "score"])


def test_former_gate_only_metrics_do_not_affect_scores(monkeypatch):
    panel = make_panel()
    monkeypatch.setattr(champions, "load_panel", lambda columns: panel[columns].copy())
    baseline = champions.screen(as_of="2026-06-01").set_index("symbol")["score"]

    panel.loc[panel["symbol"] == "EXPENSIVE", "roic_floor_5y"] = -10.0
    changed = champions.screen(as_of="2026-06-01").set_index("symbol")["score"]

    pd.testing.assert_series_equal(changed, baseline)
