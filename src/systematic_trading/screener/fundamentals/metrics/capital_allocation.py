"""Capital allocation metrics: reinvestment into the business and returns to owners."""

import pandas as pd

from systematic_trading.screener.fundamentals.metrics.helpers import (
    LAGS_3Y,
    LAGS_5Y,
    rolling,
    safe_ratio,
    shift,
    span_ok,
)

INCREMENTAL_CAPITAL_FLOOR = 0.02


def add_reinvestment(panel: pd.DataFrame) -> pd.DataFrame:
    """Reinvestment and margin stability metrics."""
    nopat_then = shift(panel, "nopat_ttm", LAGS_5Y)
    capital_then = shift(panel, "invested_capital", LAGS_5Y)
    capital_added = panel["invested_capital"] - capital_then

    grew = capital_added > INCREMENTAL_CAPITAL_FLOOR * capital_then.abs()
    panel["incremental_roic_5y"] = ((panel["nopat_ttm"] - nopat_then) / capital_added).where(grew)
    panel["incremental_roic_5y"] = panel["incremental_roic_5y"].where(span_ok(panel, LAGS_5Y))

    capex_out = (-panel["capitalExpenditure_ttm"]).clip(lower=0)
    acquisitions_out = (-panel["acquisitionsNet_ttm"]).clip(lower=0)
    panel["reinvestment_rate_ttm"] = safe_ratio(
        capex_out + acquisitions_out, panel["operatingCashFlow_ttm"]
    )

    panel["gross_margin_ttm"] = safe_ratio(panel["grossProfit_ttm"], panel["revenue_ttm"])
    margin_std = rolling(panel, "gross_margin_ttm", LAGS_5Y, 16, "std")
    panel["gross_margin_std_5y"] = margin_std.where(span_ok(panel, LAGS_5Y - 1))

    panel["operating_margin_ttm"] = safe_ratio(panel["operatingIncome_ttm"], panel["revenue_ttm"])
    panel["operating_margin_change_3y"] = (
        panel["operating_margin_ttm"] - shift(panel, "operating_margin_ttm", LAGS_3Y)
    ).where(span_ok(panel, LAGS_3Y))

    return panel


def add_payout(panel: pd.DataFrame) -> pd.DataFrame:
    """Capital return metrics."""
    # Cash returned to owners: dividends plus net buybacks. Both flows are
    # statement outflows when positive for owners, so flip the sign.
    returned = -(panel["netDividendsPaid"] + panel["netStockIssuance"])

    returned_5y = returned.groupby(panel["symbol"], sort=False).transform(
        lambda s: s.rolling(LAGS_5Y, min_periods=LAGS_5Y).sum()
    )
    fcf_5y = rolling(panel, "freeCashFlow", LAGS_5Y, LAGS_5Y, "sum")

    panel["payout_to_fcf_5y"] = safe_ratio(returned_5y, fcf_5y).where(span_ok(panel, LAGS_5Y - 1))

    return panel
