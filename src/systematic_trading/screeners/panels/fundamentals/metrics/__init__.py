"""Point-in-time metric construction for the fundamentals panel."""

from __future__ import annotations

import pandas as pd

from systematic_trading.screeners.panels.fundamentals.metrics.balance import (
    add_balance_metrics,
)
from systematic_trading.screeners.panels.fundamentals.metrics.distress import (
    add_distress_metrics,
)
from systematic_trading.screeners.panels.fundamentals.metrics.flows import add_ttm_flows
from systematic_trading.screeners.panels.fundamentals.metrics.growth import add_growth_metrics
from systematic_trading.screeners.panels.fundamentals.metrics.payout import add_payout_metrics
from systematic_trading.screeners.panels.fundamentals.metrics.quality import (
    add_cash_quality_metrics,
)
from systematic_trading.screeners.panels.fundamentals.metrics.reinvestment import (
    add_reinvestment_metrics,
)
from systematic_trading.screeners.panels.fundamentals.metrics.returns import (
    add_returns_metrics,
)
from systematic_trading.screeners.panels.fundamentals.metrics.valuation import (
    add_valuation_metrics,
)

__all__ = ["add_metrics"]


def add_metrics(df: pd.DataFrame) -> None:
    """Add all derived screener metrics to a sorted statement panel in place.

    Stages are ordered by dependency: downstream groups may consume columns
    created by earlier groups.
    """
    add_ttm_flows(df)
    add_returns_metrics(df)
    add_cash_quality_metrics(df)
    add_balance_metrics(df)
    add_growth_metrics(df)
    add_reinvestment_metrics(df)
    add_payout_metrics(df)
    add_distress_metrics(df)
    add_valuation_metrics(df)
