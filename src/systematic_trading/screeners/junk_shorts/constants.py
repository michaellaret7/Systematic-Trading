"""Configuration for the Junk Shorts screen."""

# FMP sectors where the junk metrics misfire by construction: ROIC/EBITDA/accruals
# are ill-defined for banks and insurers, and rate-regulated utilities *structurally*
# run low ROIC + heavy debt + negative FCF while being terrible shorts.
EXCLUDED_SECTORS = ["Financial Services", "Real Estate", "Utilities"]

# NaN metrics fail their check (see shared.screen.passes), so every gate below
# doubles as a complete-data guard: a company we can't measure is not a short
# candidate.
DEFAULT_CRITERIA: dict[str, float] = {
    # Eligibility guard — not a junk signal; keeps the list borrowable/tradable
    # and protects against squeeze-prone micro caps if the universe ever widens.
    "marketCap_min": 500_000_000,
    # Returns on capital — persistently poor: never cleared ~cost of capital in 5y
    "roic_ttm_max": 0.06,
    "roic_ceiling_5y_max": 0.10,
    # Cash generation — weak or negative, asset-denominated so loss-makers stay defined
    "fcf_to_assets_ttm_max": 0.03,
    "fcf_positive_quarters_5y_max": 18,
    # Debt — heavy, poorly covered, and not shrinking (small amortization tolerated)
    "debt_to_assets_min": 0.25,
    "interest_coverage_max": 5.0,
    "debt_buildup_3y_min": -0.02,
    # ... while the business stands still: at least one down revenue year of five
    "revenue_growth_years_5y_max": 4,
}

# Metric -> +1 if higher means more junk, -1 if lower means more junk.
# Accounting red flags rank here rather than gate: they are good at ordering
# badness but individually too noisy to be entry requirements.
SCORE_WEIGHTS: dict[str, int] = {
    "roic_ttm": -1,
    "roic_ceiling_5y": -1,
    "fcf_to_assets_ttm": -1,
    "interest_coverage": -1,
    "current_ratio": -1,
    "cash_runway_quarters": -1,
    "debt_to_assets": 1,
    "debt_buildup_3y": 1,
    "accruals_ratio_ttm": 1,
    "dso_change_3y": 1,
    "dio_change_3y": 1,
    "share_change_3y": 1,
}

# Columns shown in the post-build preview.
PREVIEW_COLUMNS = [
    "symbol",
    "score",
    "sector",
    "roic_ttm",
    "fcf_to_assets_ttm",
    "debt_to_assets",
    "interest_coverage",
    "debt_buildup_3y",
]
