"""Configuration for the Cashflow Champions panel and screen."""

PANEL_KEY = "screeners/cashflow_champions.parquet"

INCOME_COLUMNS = [
    "symbol",
    "date",
    "acceptedDate",
    "revenue",
    "grossProfit",
    "ebit",
    "interestExpense",
    "incomeTaxExpense",
    "incomeBeforeTax",
    "netIncome",
    "weightedAverageShsOutDil",
]

BALANCE_COLUMNS = [
    "symbol",
    "date",
    "acceptedDate",
    "totalAssets",
    "totalDebt",
    "netDebt",
    "totalEquity",
    "cashAndShortTermInvestments",
    "netReceivables",
]

CASHFLOW_COLUMNS = [
    "symbol",
    "date",
    "acceptedDate",
    "operatingCashFlow",
    "capitalExpenditure",
    "freeCashFlow",
    "acquisitionsNet",
    "stockBasedCompensation",
    "depreciationAndAmortization",
    "netDividendsPaid",
    "netStockIssuance",
]

# Joined for valuation context only; key-metrics rows carry no acceptedDate, but
# period-end market cap was public at filing time, so no look-ahead is introduced.
KEY_METRICS_COLUMNS = [
    "symbol",
    "date",
    "marketCap",
    "enterpriseValue",
]

TTM_FLOWS = [
    "revenue",
    "grossProfit",
    "ebit",
    "interestExpense",
    "incomeTaxExpense",
    "incomeBeforeTax",
    "netIncome",
    "operatingCashFlow",
    "capitalExpenditure",
    "freeCashFlow",
    "acquisitionsNet",
    "stockBasedCompensation",
    "depreciationAndAmortization",
]

# A window of n quarter-lags is only trusted if its calendar span is plausible.
MAX_SPAN_DAYS_PER_LAG = 98
MAX_SPAN_SLACK_DAYS = 40

MAX_STALENESS_DAYS = 270
TAX_RATE_CAP = 0.50
INCREMENTAL_CAPITAL_FLOOR = 0.02

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
