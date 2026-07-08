"""Load and run the Cashflow Champions screen."""

from __future__ import annotations

import numpy as np
import pandas as pd

from systematic_trading.config import s3_bucket
from systematic_trading.screeners.csf_champions.constants import (
    DEFAULT_CRITERIA,
    MAX_STALENESS_DAYS,
    PANEL_KEY,
    SCORE_WEIGHTS,
)


def panel_uri() -> str:
    """S3 location of the built Cashflow Champions panel."""
    return f"s3://{s3_bucket()}/{PANEL_KEY}"


def load_panel() -> pd.DataFrame:
    """Read the full Cashflow Champions metrics panel from S3."""
    return pd.read_parquet(panel_uri())


def screen(
    panel: pd.DataFrame | None = None,
    as_of: pd.Timestamp | str | None = None,
    criteria: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Return Cashflow Champions visible at ``as_of``, ranked by composite score."""
    panel = load_panel() if panel is None else panel
    cutoff = pd.Timestamp(as_of) if as_of is not None else panel["available_from"].max()
    criteria = {**DEFAULT_CRITERIA, **(criteria or {})}

    snapshot = _latest_visible_snapshot(panel, cutoff)
    snapshot = _drop_stale_rows(snapshot, cutoff)

    snapshot["score"] = _composite_score(snapshot)
    champions = snapshot[_passes(snapshot, criteria)]

    return champions.sort_values("score", ascending=False, ignore_index=True)


def _latest_visible_snapshot(panel: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    visible = panel[panel["available_from"] <= cutoff]

    return visible.sort_values("date").groupby("symbol", sort=False).tail(1).copy()


def _drop_stale_rows(snapshot: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    fresh = snapshot["date"] >= cutoff - pd.Timedelta(days=MAX_STALENESS_DAYS)

    return snapshot[fresh].copy()


def _composite_score(snapshot: pd.DataFrame) -> pd.Series:
    ranks = pd.DataFrame(index=snapshot.index)

    for column, sign in SCORE_WEIGHTS.items():
        ranks[column] = (sign * snapshot[column]).rank(pct=True)

    return (ranks.mean(axis=1, skipna=True) * 100.0).round(1)


def _passes(snapshot: pd.DataFrame, criteria: dict[str, float]) -> pd.Series:
    checks = [
        snapshot["roic_ttm"] >= criteria["roic_ttm_min"],
        snapshot["roic_floor_5y"] >= criteria["roic_floor_5y_min"],
        snapshot["fcf_margin_ttm"] >= criteria["fcf_margin_ttm_min"],
        snapshot["income_quality_ttm"] >= criteria["income_quality_ttm_min"],
        snapshot["fcf_positive_quarters_5y"] >= criteria["fcf_positive_quarters_5y_min"],
        snapshot["accruals_ratio_ttm"] <= criteria["accruals_ratio_ttm_max"],
        snapshot["dso_change_3y"] <= criteria["dso_change_3y_max"],
        snapshot["sbc_to_revenue_ttm"] <= criteria["sbc_to_revenue_ttm_max"],
        snapshot["net_debt_to_ebitda"] <= criteria["net_debt_to_ebitda_max"],
        snapshot["interest_coverage"] >= criteria["interest_coverage_min"],
        snapshot["revenue_cagr_5y"] >= criteria["revenue_cagr_5y_min"],
        snapshot["revenue_growth_years_5y"] >= criteria["revenue_growth_years_5y_min"],
        snapshot["fcf_ps_cagr_5y"] >= criteria["fcf_ps_cagr_5y_min"],
        snapshot["share_change_3y"] <= criteria["share_change_3y_max"],
    ]

    return pd.Series(np.logical_and.reduce(checks), index=snapshot.index)
