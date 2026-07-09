"""Panel-agnostic screen machinery: snapshots, staleness, gating, and scoring.

Each screener package owns its opinions (which metrics to gate, thresholds, score
weights); this module owns the mechanics that are identical across screeners.

Panel contract: a DataFrame with one row per ``(symbol, date)``, an
``available_from`` timestamp marking when the row became publicly knowable, and
numeric metric columns. Any panel meeting that contract can be screened.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from systematic_trading.screeners.shared.criteria import CriteriaInput, normalize_criteria
from systematic_trading.screeners.shared.validation import require_columns


def run_screen(
    panel: pd.DataFrame,
    as_of: pd.Timestamp | str | None,
    criteria: CriteriaInput,
    score_weights: dict[str, int],
    max_staleness_days: int,
    excluded_sectors: Sequence[str] = (),
    drop_missing_sector: bool = False,
) -> pd.DataFrame:
    """The standard screen pipeline over any metrics panel.

    Takes each symbol's latest row visible at ``as_of`` (defaults to the panel's
    newest filing), drops stale listings, optionally drops excluded sectors,
    scores the cross-section, and returns rows passing every criterion, ranked
    by score descending.
    """
    cutoff = pd.Timestamp(as_of) if as_of is not None else panel["available_from"].max()

    snapshot = latest_visible_snapshot(panel, cutoff)
    snapshot = drop_stale_rows(snapshot, cutoff, max_staleness_days)

    if excluded_sectors or drop_missing_sector:
        snapshot = drop_sectors(snapshot, excluded_sectors, drop_missing_sector)

    snapshot["score"] = composite_score(snapshot, score_weights)
    matches = snapshot[passes(snapshot, criteria)]

    return matches.sort_values("score", ascending=False, ignore_index=True)


def latest_visible_snapshot(panel: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Each symbol's most recent row whose filing was public at ``cutoff``."""
    visible = panel[panel["available_from"] <= cutoff]

    return visible.sort_values("date").groupby("symbol", sort=False).tail(1).copy()


def drop_stale_rows(
    snapshot: pd.DataFrame,
    cutoff: pd.Timestamp,
    max_staleness_days: int,
) -> pd.DataFrame:
    """Drop symbols whose latest fiscal quarter is older than ``max_staleness_days``."""
    fresh = snapshot["date"] >= cutoff - pd.Timedelta(days=max_staleness_days)

    return snapshot[fresh].copy()


def drop_sectors(
    snapshot: pd.DataFrame,
    excluded_sectors: Sequence[str],
    drop_missing_sector: bool = False,
) -> pd.DataFrame:
    """Drop rows in excluded sectors.

    By default, rows with no sector stay in: absence of sector data is not
    evidence the company belongs to an excluded sector. Short-side screens can
    ask to drop missing sectors because sector false negatives are costly there.
    """
    require_columns(snapshot, ["sector"], "sector filter snapshot")

    keep = ~snapshot["sector"].isin(excluded_sectors)
    if drop_missing_sector:
        keep &= snapshot["sector"].notna()

    return snapshot[keep].copy()


def composite_score(snapshot: pd.DataFrame, score_weights: dict[str, int]) -> pd.Series:
    """Cross-sectional percentile-rank composite, 0-100.

    ``score_weights`` maps metric column -> +1 if higher raises the score, -1 if
    lower raises it. NaN metrics are skipped per row, never penalized.
    """
    require_columns(snapshot, score_weights, "score snapshot")

    ranks = pd.DataFrame(index=snapshot.index)

    for column, sign in score_weights.items():
        ranks[column] = (sign * snapshot[column]).rank(pct=True)

    return (ranks.mean(axis=1, skipna=True) * 100.0).round(1)


def passes(snapshot: pd.DataFrame, criteria: CriteriaInput) -> pd.Series:
    """True where a row satisfies every criterion; NaN metrics fail their check.

    Criterion keys name a metric column plus a ``_min``/``_max`` suffix, e.g.
    ``"roic_ttm_min": 0.15`` requires ``snapshot["roic_ttm"] >= 0.15``.
    """
    normalized = normalize_criteria(criteria)
    require_columns(snapshot, (criterion.column for criterion in normalized), "criteria snapshot")

    result = pd.Series(True, index=snapshot.index)

    for criterion in normalized:
        result &= criterion.evaluate(snapshot)

    return result
