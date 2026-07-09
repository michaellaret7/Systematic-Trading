"""The Cashflow Champions screen: durable, self-funding compounders.

Gates on high and stable returns on capital, real cash conversion, clean
accounting, a fortress balance sheet, and per-share growth without dilution.
Methodology doc: docs/screeners/cashflow_champions.md.
"""

import pandas as pd

from systematic_trading.screener.fundamentals import load_panel
from systematic_trading.screener.fundamentals.screen import run_screen

DEFAULT_CRITERIA: dict[str, float] = {
    "roic_ttm_min": 0.15,
    "roic_floor_5y_min": 0.10,
    "fcf_margin_ttm_min": 0.05,
    "income_quality_ttm_min": 1.0,
    "fcf_positive_quarters_5y_min": 18,
    "accruals_ratio_ttm_max": 0.10,
    "dso_change_3y_max": 15.0,
    "sbc_to_revenue_ttm_max": 0.15,
    "net_debt_to_ebitda_max": 1.5,
    "interest_coverage_min": 10.0,
    "revenue_cagr_5y_min": 0.05,
    "revenue_growth_years_5y_min": 4,
    "fcf_ps_cagr_5y_min": 0.05,
    "share_change_3y_max": 0.05,
}

# Metric -> +1 if higher is better, -1 if lower is better.
SCORE_WEIGHTS: dict[str, int] = {
    "roic_ttm": 1,
    "incremental_roic_5y": 1,
    "gross_profitability_ttm": 1,
    "payout_to_fcf_5y": 1,
    "fcf_margin_ttm": 1,
    "income_quality_ttm": 1,
    "revenue_cagr_5y": 1,
    "fcf_ps_cagr_5y": 1,
    "accruals_ratio_ttm": -1,
    "net_debt_to_ebitda": -1,
    "gross_margin_std_5y": -1,
    "sbc_to_revenue_ttm": -1,
}

IDENTITY_COLUMNS = ["symbol", "date", "filingDate", "sector", "industry"]

# Not gated or scored, but useful context in the output.
CONTEXT_COLUMNS = ["marketCap", "fcf_yield_ttm", "ev_to_ebitda_ttm"]


def needed_columns(criteria: dict[str, float]) -> list[str]:
    """Panel columns this screen needs: identity plus every gated or scored metric."""
    gated = [key.rpartition("_")[0] for key in criteria]

    return list(dict.fromkeys(IDENTITY_COLUMNS + CONTEXT_COLUMNS + gated + list(SCORE_WEIGHTS)))


def screen(
    as_of: pd.Timestamp | str | None = None,
    criteria: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Return Cashflow Champions visible at ``as_of``, ranked by composite score."""
    criteria = {**DEFAULT_CRITERIA, **(criteria or {})}
    panel = load_panel(columns=needed_columns(criteria))

    return run_screen(panel, criteria=criteria, score_weights=SCORE_WEIGHTS, as_of=as_of)


if __name__ == "__main__":
    champions = screen()
    print(champions.head(10))
    
