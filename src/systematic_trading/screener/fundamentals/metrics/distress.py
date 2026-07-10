"""Short-side distress metrics."""

import pandas as pd

from systematic_trading.screener.fundamentals.metrics.helpers import (
    LAGS_3Y,
    LAGS_5Y,
    avg_4q,
    rolling,
    safe_ratio,
    shift,
    span_ok,
)


def add_distress(panel: pd.DataFrame) -> pd.DataFrame:
    """Short-side distress metrics."""
    # Denominate in total assets wherever possible: revenue, EBITDA, and net
    # income go to zero or negative on exactly the companies a short screen targets.
    ceiling = rolling(panel, "roic_ttm", LAGS_5Y, 16, "max")
    panel["roic_ceiling_5y"] = ceiling.where(span_ok(panel, LAGS_5Y - 1))

    panel["debt_to_assets"] = safe_ratio(panel["totalDebt"], panel["totalAssets"])

    avg_assets = avg_4q(panel, "totalAssets")
    panel["fcf_to_assets_ttm"] = safe_ratio(panel["freeCashFlow_ttm"], avg_assets)

    # Debt added over three years, scaled by the asset base it was added to.
    debt_added = panel["totalDebt"] - shift(panel, "totalDebt", LAGS_3Y)
    assets_then = shift(panel, "totalAssets", LAGS_3Y)
    panel["debt_buildup_3y"] = safe_ratio(debt_added, assets_then).where(span_ok(panel, LAGS_3Y))

    # Net-debt version of the same flag: cash drawdowns count as deterioration too.
    net_debt_added = panel["netDebt"] - shift(panel, "netDebt", LAGS_3Y)
    panel["net_debt_change_3y"] = safe_ratio(net_debt_added, assets_then).where(
        span_ok(panel, LAGS_3Y)
    )

    panel["current_ratio"] = safe_ratio(
        panel["totalCurrentAssets"], panel["totalCurrentLiabilities"]
    )

    # Quarters of cash left at the TTM burn rate; NaN when TTM FCF is positive.
    burn_per_quarter = (-panel["freeCashFlow_ttm"] / 4.0).where(panel["freeCashFlow_ttm"] < 0)
    panel["cash_runway_quarters"] = safe_ratio(
        panel["cashAndShortTermInvestments"], burn_per_quarter
    )

    # Altman Z (1968 form) as a coarse distress gate; any missing input NaNs the score.
    working_capital = panel["totalCurrentAssets"] - panel["totalCurrentLiabilities"]
    panel["altman_z"] = (
        1.2 * safe_ratio(working_capital, panel["totalAssets"])
        + 1.4 * safe_ratio(panel["retainedEarnings"], panel["totalAssets"])
        + 3.3 * safe_ratio(panel["ebit_ttm"], panel["totalAssets"])
        + 0.6 * safe_ratio(panel["marketCap"], panel["totalLiabilities"])
        + 1.0 * safe_ratio(panel["revenue_ttm"], panel["totalAssets"])
    )

    return panel
