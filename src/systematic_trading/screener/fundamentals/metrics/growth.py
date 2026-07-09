"""Growth and dilution metrics."""

import pandas as pd

from systematic_trading.screener.fundamentals.metrics.helpers import (
    LAGS_3Y,
    LAGS_5Y,
    cagr,
    safe_ratio,
    shift,
    span_ok,
)


def add_growth(panel: pd.DataFrame) -> pd.DataFrame:
    """Growth and dilution metrics."""
    ok_5y = span_ok(panel, LAGS_5Y)

    revenue_then = shift(panel, "revenue_ttm", LAGS_5Y)
    panel["revenue_cagr_5y"] = cagr(panel["revenue_ttm"], revenue_then, 5).where(ok_5y)

    panel["fcf_per_share_ttm"] = safe_ratio(panel["freeCashFlow_ttm"], panel["shares_ttm"])
    fcf_ps_then = shift(panel, "fcf_per_share_ttm", LAGS_5Y)
    panel["fcf_ps_cagr_5y"] = cagr(panel["fcf_per_share_ttm"], fcf_ps_then, 5).where(ok_5y)

    year_ago = shift(panel, "revenue_ttm", 4)
    yoy_positive = (panel["revenue_ttm"] > year_ago).astype(float).where(year_ago.notna())

    grouped_yoy = yoy_positive.groupby(panel["symbol"], sort=False)
    lagged = [grouped_yoy.shift(lag) for lag in (0, 4, 8, 12, 16)]
    panel["revenue_growth_years_5y"] = pd.concat(lagged, axis=1).sum(axis=1, skipna=False)
    panel["revenue_growth_years_5y"] = panel["revenue_growth_years_5y"].where(ok_5y)

    shares_then = shift(panel, "shares_ttm", LAGS_3Y)
    panel["share_change_3y"] = (panel["shares_ttm"] / shares_then - 1.0).where(
        span_ok(panel, LAGS_3Y)
    )

    return panel
