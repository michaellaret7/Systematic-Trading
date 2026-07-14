"""Rank durable, self-funding compounders on quality and valuation."""

import pandas as pd

from systematic_trading.data.repository import load_panel
from systematic_trading.screener.fundamentals.screen import run_screen

# Metric weight: sign sets direction, magnitude sets influence within the pillar.
# Leverage remains context rather than a scored return factor.
QUALITY_SCORE_WEIGHTS: dict[str, float] = {
    "roic_ttm": 1,
    "incremental_roic_5y": 1,
    "gross_profitability_ttm": 1,
    "payout_to_fcf_5y": 1,
    "fcf_margin_ttm": 1,
    "income_quality_ttm": 1,
    "revenue_cagr_5y": 1,
    "fcf_ps_cagr_5y": 1,
    "accruals_ratio_ttm": -1,
    "gross_margin_std_5y": -1,
    "sbc_to_revenue_ttm": -1,
}

# Cash yield is adjusted for SBC so the valuation and quality definitions use
# the same owner-cost treatment. All value metrics are required for ranking.
VALUE_SCORE_WEIGHTS: dict[str, float] = {
    "fcf_adj_yield_ttm": 0.50,
    "earnings_yield_ttm": 0.25,
    "ev_to_ebitda_ttm": -0.25,
}

SCORE_GROUPS = {
    "quality": QUALITY_SCORE_WEIGHTS,
    "value": VALUE_SCORE_WEIGHTS,
}
SCORE_GROUP_WEIGHTS = {"quality": 0.60, "value": 0.40}

IDENTITY_COLUMNS = ["symbol", "date", "filingDate", "sector", "industry"]

# Not gated or scored, but useful context in the output.
CONTEXT_COLUMNS = [
    "marketCap",
    "fcf_yield_ttm",
    "ev_to_ebitda_ttm",
    "fcf_adj_yield_ttm",
    "earnings_yield_ttm",
    "owner_earnings_yield_ttm",
    "roic_floor_5y",
    "fcf_adj_margin_ttm",
    "fcf_positive_quarters_5y",
    "dso_change_3y",
    "net_debt_to_ebitda",
    "interest_coverage",
    "revenue_growth_years_5y",
    "share_change_3y",
    "roce_ttm",
    "croic_ttm",
    "roic_ex_goodwill_ttm",
    "roic_cash_tax_ttm",
    "rnd_adj_roic_ttm",
    "roic_trend_3y",
    "net_debt_to_fcf",
    "altman_z",
    "ccc_ttm",
    "operating_margin_ttm",
]

# Computed in-screen as <column>_vs_sector: the spread over the sector median.
SECTOR_RELATIVE_COLUMNS = ("roic_ttm",)

DISPLAY_COLUMNS = [
    "symbol",
    "quality_score",
    "value_score",
    "score",
    "fcf_yield_ttm",
    "fcf_adj_yield_ttm",
    "earnings_yield_ttm",
    "owner_earnings_yield_ttm",
    "ev_to_ebitda_ttm",
]


def needed_columns() -> list[str]:
    """Panel columns this screen needs for identity, context, and scoring."""
    scored = [column for weights in SCORE_GROUPS.values() for column in weights]

    return list(dict.fromkeys(IDENTITY_COLUMNS + CONTEXT_COLUMNS + scored))


def screen(
    as_of: pd.Timestamp | str | None = None,
) -> pd.DataFrame:
    """Rank the full market by a 60/40 quality-value composite."""
    panel = load_panel(columns=needed_columns())

    return run_screen(
        panel,
        as_of=as_of,
        sector_relative_columns=SECTOR_RELATIVE_COLUMNS,
        score_groups=SCORE_GROUPS,
        score_group_weights=SCORE_GROUP_WEIGHTS,
        complete_score_groups=("value",),
    )


if __name__ == "__main__":
    champions = screen(as_of="2025-07-09")
    print(champions.head(100)[DISPLAY_COLUMNS].to_string(index=False))
