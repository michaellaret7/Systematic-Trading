"""Agent tool: pull raw FMP fundamental statements from the S3 parquet repository.

Loads one statement (income / balance / cashflow / key_metrics / ratios) for one
ticker over a date range and returns it as YAML tabular data for the agent to
ingest. All parquet I/O goes through ``data.repository`` — this module never
builds S3 URIs or calls ``read_parquet`` itself.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal, Optional

import pandas as pd
import yaml
from agent_harness.decorator import Param, agent_tool

from systematic_trading.data.repository import load_statement, statement_columns

#     ================================
# --> Helper funcs
#     ================================


def _parse_date(value: str) -> pd.Timestamp | None:
    """Parse an ISO date string; None signals a bad input the tool reports as an error."""
    try:
        parsed = pd.Timestamp(value)
    except ValueError:
        return None

    return parsed if isinstance(parsed, pd.Timestamp) else None


# File schemas are static within a process; caching skips the footer round trip
# on every call after the first for a given (statement, period).
_SCHEMA_CACHE: dict[tuple[str, str], list[str]] = {}


def _valid_columns(statement: str, period: str) -> list[str]:
    """Column names of one statement file, cached per process."""
    key = (statement, period)

    if key not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[key] = statement_columns(statement, period)

    return _SCHEMA_CACHE[key]


def _missing_columns(requested: list[str], available: list[str]) -> list[str]:
    """Requested column names that don't exist in the statement file."""
    return [column for column in requested if column not in available]


def _frame_to_records(frame: pd.DataFrame) -> list[dict]:
    """DataFrame -> plain-python records: ISO date strings, NaN -> null, no numpy scalars."""
    frame = frame.copy()

    for column in frame.columns:
        if pd.api.types.is_datetime64_any_dtype(frame[column]):
            frame[column] = frame[column].dt.strftime("%Y-%m-%d")

    # Round-trip through JSON so numpy scalars become plain python and NaN becomes null.
    return json.loads(frame.to_json(orient="records") or "[]")


#     ================================
# --> Tool
#     ================================


@agent_tool(name="GetFundamentalStatement", safe_parallel=True)
def get_fundamental_statement(
    statement: Annotated[
        Literal["income", "balance", "cashflow", "key_metrics", "ratios"],
        Param(description="Which fundamental statement to pull."),
    ],
    ticker: Annotated[str, Param(description="Ticker symbol, e.g. 'AAPL'.")],
    start_date: Annotated[
        str, Param(description="Start of the date range (inclusive), ISO format YYYY-MM-DD.")
    ],
    end_date: Annotated[
        str, Param(description="End of the date range (inclusive), ISO format YYYY-MM-DD.")
    ],
    period: Annotated[
        Literal["quarter", "annual"],
        Param(description="Reporting cadence: 'quarter' for quarterly rows, 'annual' for yearly."),
    ] = "quarter",
    # Optional[...] not `| None`: the decorator's schema builder only unwraps
    # typing.Union, so a PEP 604 union would degrade the schema type to string.
    columns: Annotated[
        Optional[list[str]],
        Param(
            description=(
                "Optional list of column names to return, e.g. ['eps', 'epsDiluted', "
                "'incomeTaxExpense']. Omit to get every column. The 'date' column is "
                "always included. Unknown names return an error listing the valid columns."
            )
        ),
    ] = None,
) -> str:
    """
    Pull raw FMP fundamental statement data for one ticker from the S3 parquet
    repository. Returns every fiscal period whose period-end date falls inside
    [start_date, end_date] as YAML tabular data: header keys (ticker,
    statement, period) followed by a `rows` list, one mapping per fiscal
    period, oldest first. Missing values are null.

    Prefer passing `columns` to fetch only the fields you need — omitting it
    returns every column in the file, which is rarely worth the context. Use
    the exact names from the listing below; never guess or invent names. The
    `date` column (fiscal period end) is always included so rows stay anchored
    to their period. Bad inputs return an "error: ..." string; an unknown
    column name returns an error listing every valid column so you can correct
    it and retry.

    Available columns per statement:

    income:
      date, symbol, reportedCurrency, cik, filingDate, acceptedDate, fiscalYear, period,
      revenue, costOfRevenue, grossProfit, researchAndDevelopmentExpenses,
      generalAndAdministrativeExpenses, sellingAndMarketingExpenses,
      sellingGeneralAndAdministrativeExpenses, otherExpenses, operatingExpenses,
      costAndExpenses, netInterestIncome, interestIncome, interestExpense,
      depreciationAndAmortization, ebitda, ebit, nonOperatingIncomeExcludingInterest,
      operatingIncome, totalOtherIncomeExpensesNet, incomeBeforeTax, incomeTaxExpense,
      netIncomeFromContinuingOperations, netIncomeFromDiscontinuedOperations,
      otherAdjustmentsToNetIncome, netIncome, netIncomeDeductions, bottomLineNetIncome, eps,
      epsDiluted, weightedAverageShsOut, weightedAverageShsOutDil

    balance:
      date, symbol, reportedCurrency, cik, filingDate, acceptedDate, fiscalYear, period,
      cashAndCashEquivalents, shortTermInvestments, cashAndShortTermInvestments,
      netReceivables, accountsReceivables, otherReceivables, inventory, prepaids,
      otherCurrentAssets, totalCurrentAssets, propertyPlantEquipmentNet, goodwill,
      intangibleAssets, goodwillAndIntangibleAssets, longTermInvestments, taxAssets,
      otherNonCurrentAssets, totalNonCurrentAssets, otherAssets, totalAssets, totalPayables,
      accountPayables, otherPayables, accruedExpenses, shortTermDebt,
      capitalLeaseObligationsCurrent, taxPayables, deferredRevenue, otherCurrentLiabilities,
      totalCurrentLiabilities, longTermDebt, capitalLeaseObligationsNonCurrent,
      deferredRevenueNonCurrent, deferredTaxLiabilitiesNonCurrent, otherNonCurrentLiabilities,
      totalNonCurrentLiabilities, otherLiabilities, capitalLeaseObligations, totalLiabilities,
      treasuryStock, preferredStock, commonStock, retainedEarnings, additionalPaidInCapital,
      accumulatedOtherComprehensiveIncomeLoss, otherTotalStockholdersEquity,
      totalStockholdersEquity, totalEquity, minorityInterest, totalLiabilitiesAndTotalEquity,
      totalInvestments, totalDebt, netDebt

    cashflow:
      date, symbol, reportedCurrency, cik, filingDate, acceptedDate, fiscalYear, period,
      netIncome, depreciationAndAmortization, deferredIncomeTax, stockBasedCompensation,
      changeInWorkingCapital, accountsReceivables, inventory, accountsPayables,
      otherWorkingCapital, otherNonCashItems, netCashProvidedByOperatingActivities,
      investmentsInPropertyPlantAndEquipment, acquisitionsNet, purchasesOfInvestments,
      salesMaturitiesOfInvestments, otherInvestingActivities,
      netCashProvidedByInvestingActivities, netDebtIssuance, longTermNetDebtIssuance,
      shortTermNetDebtIssuance, netStockIssuance, netCommonStockIssuance, commonStockIssuance,
      commonStockRepurchased, netPreferredStockIssuance, netDividendsPaid, commonDividendsPaid,
      preferredDividendsPaid, otherFinancingActivities, netCashProvidedByFinancingActivities,
      effectOfForexChangesOnCash, netChangeInCash, cashAtEndOfPeriod, cashAtBeginningOfPeriod,
      operatingCashFlow, capitalExpenditure, freeCashFlow, incomeTaxesPaid, interestPaid

    key_metrics:
      symbol, date, fiscalYear, period, reportedCurrency, marketCap, enterpriseValue,
      evToSales, evToOperatingCashFlow, evToFreeCashFlow, evToEBITDA, netDebtToEBITDA,
      currentRatio, incomeQuality, grahamNumber, grahamNetNet, taxBurden, interestBurden,
      workingCapital, investedCapital, returnOnAssets, operatingReturnOnAssets,
      returnOnTangibleAssets, returnOnEquity, returnOnInvestedCapital, returnOnCapitalEmployed,
      earningsYield, freeCashFlowYield, capexToOperatingCashFlow, capexToDepreciation,
      capexToRevenue, salesGeneralAndAdministrativeToRevenue, researchAndDevelopementToRevenue,
      stockBasedCompensationToRevenue, intangiblesToTotalAssets, averageReceivables,
      averagePayables, averageInventory, daysOfSalesOutstanding, daysOfPayablesOutstanding,
      daysOfInventoryOutstanding, operatingCycle, cashConversionCycle, freeCashFlowToEquity,
      freeCashFlowToFirm, tangibleAssetValue, netCurrentAssetValue

    ratios:
      symbol, date, fiscalYear, period, reportedCurrency, grossProfitMargin, ebitMargin,
      ebitdaMargin, operatingProfitMargin, pretaxProfitMargin,
      continuousOperationsProfitMargin, netProfitMargin, bottomLineProfitMargin,
      receivablesTurnover, payablesTurnover, inventoryTurnover, fixedAssetTurnover,
      assetTurnover, currentRatio, quickRatio, solvencyRatio, cashRatio, priceToEarningsRatio,
      priceToEarningsGrowthRatio, forwardPriceToEarningsGrowthRatio, priceToBookRatio,
      priceToSalesRatio, priceToFreeCashFlowRatio, priceToOperatingCashFlowRatio,
      debtToAssetsRatio, debtToEquityRatio, debtToCapitalRatio, longTermDebtToCapitalRatio,
      financialLeverageRatio, workingCapitalTurnoverRatio, operatingCashFlowRatio,
      operatingCashFlowSalesRatio, freeCashFlowOperatingCashFlowRatio,
      debtServiceCoverageRatio, interestCoverageRatio, shortTermOperatingCashFlowCoverageRatio,
      operatingCashFlowCoverageRatio, capitalExpenditureCoverageRatio,
      dividendPaidAndCapexCoverageRatio, dividendPayoutRatio, dividendYield,
      dividendYieldPercentage, revenuePerShare, netIncomePerShare, interestDebtPerShare,
      cashPerShare, bookValuePerShare, tangibleBookValuePerShare, shareholdersEquityPerShare,
      operatingCashFlowPerShare, capexPerShare, freeCashFlowPerShare, netIncomePerEBT,
      ebtPerEbit, priceToFairValue, debtToMarketCap, effectiveTaxRate, enterpriseValueMultiple,
      dividendPerShare
    """
    start = _parse_date(start_date)
    end = _parse_date(end_date)

    if start is None:
        return f"error: start_date {start_date!r} is not a valid ISO date (YYYY-MM-DD)"

    if end is None:
        return f"error: end_date {end_date!r} is not a valid ISO date (YYYY-MM-DD)"

    if start > end:
        return f"error: start_date {start_date!r} is after end_date {end_date!r}"

    symbol = ticker.strip().upper()

    # Validate against the parquet footer (schema-only read, cached), then pull
    # just the projected columns for just this symbol — never the whole file.
    if columns:
        valid = _valid_columns(statement, period)
        missing = _missing_columns(columns, valid)

        if missing:
            return (
                f"error: unknown column(s) {missing} for {statement} ({period}); "
                f"valid columns: {', '.join(valid)}"
            )

    keep = None

    if columns:
        keep = ["date"] + [column for column in columns if column not in ("date", "symbol")]

    frame = load_statement(statement, period, columns=keep, symbol=symbol)

    if frame.empty:
        return f"error: no {statement} ({period}) data for ticker {symbol!r}"

    rows = frame.loc[(frame["date"] >= start) & (frame["date"] <= end)]

    if rows.empty:
        return (
            f"error: no {statement} ({period}) rows for {symbol} "
            f"between {start_date} and {end_date}"
        )

    rows = rows.sort_values("date")

    if keep is None:
        rows = rows.drop(columns=["symbol"])

    payload = {
        "ticker": symbol,
        "statement": statement,
        "period": period,
        "rows": _frame_to_records(rows),
    }

    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
