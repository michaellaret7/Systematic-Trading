"""Capital return metrics."""

from __future__ import annotations

import pandas as pd

from systematic_trading.screeners.panels.fundamentals.metrics.helpers import (
    grouped,
    safe_ratio,
    span_ok,
)


def add_payout_metrics(df: pd.DataFrame) -> None:
    # Cash returned to owners: dividends plus net buybacks. Both flows are
    # statement outflows when positive for owners, so flip the sign.
    returned = -(df["netDividendsPaid"] + df["netStockIssuance"])

    returned_5y = grouped(df.assign(returned=returned), "returned").transform(
        lambda s: s.rolling(20, min_periods=20).sum()
    )
    fcf_5y = grouped(df, "freeCashFlow").transform(lambda s: s.rolling(20, min_periods=20).sum())

    df["payout_to_fcf_5y"] = safe_ratio(returned_5y, fcf_5y).where(span_ok(df, 19))
