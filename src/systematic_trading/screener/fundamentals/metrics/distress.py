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

    panel["current_ratio"] = safe_ratio(
        panel["totalCurrentAssets"], panel["totalCurrentLiabilities"]
    )

    # Quarters of cash left at the TTM burn rate; NaN when TTM FCF is positive.
    burn_per_quarter = (-panel["freeCashFlow_ttm"] / 4.0).where(panel["freeCashFlow_ttm"] < 0)
    panel["cash_runway_quarters"] = safe_ratio(
        panel["cashAndShortTermInvestments"], burn_per_quarter
    )

    cogs_ttm = panel["revenue_ttm"] - panel["grossProfit_ttm"]
    panel["dio_ttm"] = safe_ratio(panel["inventory"] * 365.0, cogs_ttm)
    panel["dio_change_3y"] = (panel["dio_ttm"] - shift(panel, "dio_ttm", LAGS_3Y)).where(
        span_ok(panel, LAGS_3Y)
    )

    return panel
