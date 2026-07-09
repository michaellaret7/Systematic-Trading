"""Metric groups for the fundamentals panel.

Every metric is recomputed from raw statement columns so the formulas are ours;
the only externally sourced inputs are ``marketCap`` and ``enterpriseValue``,
which cannot be derived from filings. Raw columns keep FMP's original names;
derived metrics are snake_case.

Each ``add_*`` function takes the merged quarterly panel and returns it with
new columns — adding a metric to the master table means adding one function in
the right group module and listing it in ``METRIC_GROUPS`` (ordered by
dependency: downstream groups may consume columns created by earlier groups).
"""

import pandas as pd

from systematic_trading.screener.fundamentals.metrics.capital_allocation import (
    add_payout,
    add_reinvestment,
)
from systematic_trading.screener.fundamentals.metrics.distress import add_distress
from systematic_trading.screener.fundamentals.metrics.flows import add_ttm_flows
from systematic_trading.screener.fundamentals.metrics.growth import add_growth
from systematic_trading.screener.fundamentals.metrics.quality import (
    add_balance,
    add_cash_quality,
)
from systematic_trading.screener.fundamentals.metrics.returns import add_returns
from systematic_trading.screener.fundamentals.metrics.valuation import add_valuation

__all__ = ["METRIC_GROUPS", "compute_metrics"]

METRIC_GROUPS = (
    add_ttm_flows,
    add_returns,
    add_cash_quality,
    add_balance,
    add_growth,
    add_reinvestment,
    add_payout,
    add_distress,
    add_valuation,
)


def compute_metrics(panel: pd.DataFrame) -> pd.DataFrame:
    """Sort the merged panel by (symbol, date) and run every metric group over it."""
    panel = panel.sort_values(["symbol", "date"]).reset_index(drop=True)

    for add_group in METRIC_GROUPS:
        panel = add_group(panel)

    return panel
