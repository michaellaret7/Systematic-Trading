"""Configuration for the fundamentals metrics panel."""

PANEL_KEY = "screeners/fundamentals_panel.parquet"

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
    "inventory",
    "totalCurrentAssets",
    "totalCurrentLiabilities",
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
