"""Point-in-time metric construction for the Cashflow Champions panel."""

from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.api.typing import SeriesGroupBy

from systematic_trading.screeners.csf_champions.constants import (
    INCREMENTAL_CAPITAL_FLOOR,
    MAX_SPAN_DAYS_PER_LAG,
    MAX_SPAN_SLACK_DAYS,
    TAX_RATE_CAP,
    TTM_FLOWS,
)


def add_metrics(df: pd.DataFrame) -> None:
    """Add all derived screener metrics to a sorted statement panel in place."""
    _add_ttm_flows(df)
    _add_returns_metrics(df)
    _add_cash_quality_metrics(df)
    _add_balance_metrics(df)
    _add_growth_metrics(df)
    _add_reinvestment_metrics(df)


def _grouped(df: pd.DataFrame, column: str) -> SeriesGroupBy:
    return df.groupby("symbol", sort=False)[column]


def _ttm(df: pd.DataFrame, column: str) -> pd.Series:
    return _grouped(df, column).transform(lambda s: s.rolling(4, min_periods=4).sum())


def _shift(df: pd.DataFrame, column: str, lags: int) -> pd.Series:
    return _grouped(df, column).shift(lags)


def _span_ok(df: pd.DataFrame, lags: int) -> pd.Series:
    span_days = (df["date"] - _shift(df, "date", lags)).dt.days
    limit = lags * MAX_SPAN_DAYS_PER_LAG + MAX_SPAN_SLACK_DAYS

    return span_days <= limit


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.where(denominator > 0)


def _cagr(now: pd.Series, then: pd.Series, years: int) -> pd.Series:
    valid = (now > 0) & (then > 0)

    return ((now / then) ** (1.0 / years) - 1.0).where(valid)


def _add_ttm_flows(df: pd.DataFrame) -> None:
    ttm_ok = _span_ok(df, 3)

    for column in TTM_FLOWS:
        df[f"{column}_ttm"] = _ttm(df, column).where(ttm_ok)

    df["shares_ttm"] = (
        _grouped(df, "weightedAverageShsOutDil")
        .transform(lambda s: s.rolling(4, min_periods=4).mean())
        .where(ttm_ok)
    )


def _add_returns_metrics(df: pd.DataFrame) -> None:
    tax_rate = _safe_ratio(df["incomeTaxExpense_ttm"], df["incomeBeforeTax_ttm"])
    tax_rate = tax_rate.clip(0.0, TAX_RATE_CAP)

    df["nopat_ttm"] = df["ebit_ttm"] * (1.0 - tax_rate)
    df["invested_capital"] = (
        df["totalDebt"] + df["totalEquity"] - df["cashAndShortTermInvestments"]
    )

    avg_capital = (df["invested_capital"] + _shift(df, "invested_capital", 4)) / 2.0
    df["roic_ttm"] = _safe_ratio(df["nopat_ttm"], avg_capital)

    floor = _grouped(df, "roic_ttm").transform(lambda s: s.rolling(20, min_periods=16).min())
    df["roic_floor_5y"] = floor.where(_span_ok(df, 19))


def _add_cash_quality_metrics(df: pd.DataFrame) -> None:
    df["fcf_margin_ttm"] = _safe_ratio(df["freeCashFlow_ttm"], df["revenue_ttm"])
    df["income_quality_ttm"] = _safe_ratio(df["operatingCashFlow_ttm"], df["netIncome_ttm"])

    positive_fcf = (df["freeCashFlow"] > 0).astype(float)
    streak = _grouped(df.assign(fcf_pos=positive_fcf), "fcf_pos").transform(
        lambda s: s.rolling(20, min_periods=20).sum()
    )
    df["fcf_positive_quarters_5y"] = streak.where(_span_ok(df, 19))

    avg_assets = (df["totalAssets"] + _shift(df, "totalAssets", 4)) / 2.0
    accruals = df["netIncome_ttm"] - df["operatingCashFlow_ttm"]
    df["accruals_ratio_ttm"] = _safe_ratio(accruals, avg_assets)

    df["dso_ttm"] = _safe_ratio(df["netReceivables"] * 365.0, df["revenue_ttm"])
    df["dso_change_3y"] = (df["dso_ttm"] - _shift(df, "dso_ttm", 12)).where(
        _span_ok(df, 12)
    )
    df["sbc_to_revenue_ttm"] = _safe_ratio(df["stockBasedCompensation_ttm"], df["revenue_ttm"])


def _add_balance_metrics(df: pd.DataFrame) -> None:
    df["ebitda_ttm"] = df["ebit_ttm"] + df["depreciationAndAmortization_ttm"]
    df["net_debt_to_ebitda"] = df["netDebt"] / df["ebitda_ttm"].where(df["ebitda_ttm"] > 0)

    coverage = _safe_ratio(df["ebit_ttm"], df["interestExpense_ttm"])
    debt_free = (df["interestExpense_ttm"] <= 0) & (df["ebit_ttm"] > 0)
    df["interest_coverage"] = coverage.mask(debt_free, np.inf)


def _add_growth_metrics(df: pd.DataFrame) -> None:
    ok_5y = _span_ok(df, 20)

    revenue_then = _shift(df, "revenue_ttm", 20)
    df["revenue_cagr_5y"] = _cagr(df["revenue_ttm"], revenue_then, 5).where(ok_5y)

    df["fcf_per_share_ttm"] = _safe_ratio(df["freeCashFlow_ttm"], df["shares_ttm"])
    fcf_ps_then = _shift(df, "fcf_per_share_ttm", 20)
    df["fcf_ps_cagr_5y"] = _cagr(df["fcf_per_share_ttm"], fcf_ps_then, 5).where(ok_5y)

    yoy_positive = (df["revenue_ttm"] > _shift(df, "revenue_ttm", 4)).astype(float)
    yoy_positive = yoy_positive.where(_shift(df, "revenue_ttm", 4).notna())

    flags = df.assign(yoy=yoy_positive)
    lagged = [_grouped(flags, "yoy").shift(lag) for lag in (0, 4, 8, 12, 16)]
    df["revenue_growth_years_5y"] = pd.concat(lagged, axis=1).sum(axis=1, skipna=False)
    df["revenue_growth_years_5y"] = df["revenue_growth_years_5y"].where(ok_5y)

    shares_then = _shift(df, "shares_ttm", 12)
    df["share_change_3y"] = (df["shares_ttm"] / shares_then - 1.0).where(_span_ok(df, 12))


def _add_reinvestment_metrics(df: pd.DataFrame) -> None:
    nopat_then = _shift(df, "nopat_ttm", 20)
    capital_then = _shift(df, "invested_capital", 20)
    capital_added = df["invested_capital"] - capital_then

    grew = capital_added > INCREMENTAL_CAPITAL_FLOOR * capital_then.abs()
    df["incremental_roic_5y"] = ((df["nopat_ttm"] - nopat_then) / capital_added).where(grew)
    df["incremental_roic_5y"] = df["incremental_roic_5y"].where(_span_ok(df, 20))

    capex_out = (-df["capitalExpenditure_ttm"]).clip(lower=0)
    acquisitions_out = (-df["acquisitionsNet_ttm"]).clip(lower=0)
    df["reinvestment_rate_ttm"] = _safe_ratio(
        capex_out + acquisitions_out,
        df["operatingCashFlow_ttm"],
    )

    df["gross_margin_ttm"] = _safe_ratio(df["grossProfit_ttm"], df["revenue_ttm"])
    margin_std = _grouped(df, "gross_margin_ttm").transform(
        lambda s: s.rolling(20, min_periods=16).std()
    )
    df["gross_margin_std_5y"] = margin_std.where(_span_ok(df, 19))
