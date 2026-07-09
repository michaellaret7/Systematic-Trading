"""Panel-agnostic screen machinery: point-in-time snapshots, gating, and scoring.

Each screener module owns its opinions (which metrics to gate, thresholds,
score weights, sector exclusions); this module owns the mechanics that are
identical across screeners.

Panel contract: a DataFrame with one row per ``(symbol, date)``, a
``filingDate`` timestamp marking when the row became publicly knowable, and
numeric metric columns. Any panel meeting that contract can be screened.
"""

import pandas as pd

# A symbol whose latest fiscal quarter is older than this at the cutoff is
# treated as dead/delisted and dropped from the cross-section.
MAX_STALENESS_DAYS = 270


def run_screen(
    panel: pd.DataFrame,
    criteria: dict[str, float],
    score_weights: dict[str, int],
    as_of: pd.Timestamp | str | None = None,
    excluded_sectors: tuple[str, ...] = (),
    drop_missing_sector: bool = False,
) -> pd.DataFrame:
    """The standard screen pipeline over any metrics panel.

    Takes each symbol's latest row visible at ``as_of`` (defaults to the
    panel's newest filing), drops stale listings, optionally drops excluded
    sectors, scores the cross-section, and returns rows passing every
    criterion, ranked by score descending.
    """
    cutoff = pd.Timestamp(as_of) if as_of is not None else panel["filingDate"].max()

    snapshot = cross_section(panel, cutoff)

    if excluded_sectors or drop_missing_sector:
        snapshot = drop_sectors(snapshot, excluded_sectors, drop_missing_sector)

    snapshot["score"] = composite_score(snapshot, score_weights)
    matches = snapshot[passes(snapshot, criteria)]

    return matches.sort_values("score", ascending=False, ignore_index=True)


def cross_section(panel: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Each symbol's freshest row publicly visible at ``cutoff``, stale symbols dropped."""
    visible = panel[panel["filingDate"] <= cutoff]
    latest = visible.sort_values("date").groupby("symbol", sort=False).tail(1)

    fresh = latest["date"] >= cutoff - pd.Timedelta(days=MAX_STALENESS_DAYS)

    return latest[fresh].copy()


def drop_sectors(
    snapshot: pd.DataFrame,
    excluded_sectors: tuple[str, ...],
    drop_missing_sector: bool = False,
) -> pd.DataFrame:
    """Drop rows in excluded sectors.

    By default, rows with no sector stay in: absence of sector data is not
    evidence the company belongs to an excluded sector. Short-side screens can
    ask to drop missing sectors because sector false negatives are costly there.
    """
    keep = ~snapshot["sector"].isin(excluded_sectors)

    if drop_missing_sector:
        keep &= snapshot["sector"].notna()

    return snapshot[keep].copy()


def composite_score(snapshot: pd.DataFrame, score_weights: dict[str, int]) -> pd.Series:
    """Cross-sectional percentile-rank composite, 0-100.

    ``score_weights`` maps metric column -> +1 if higher raises the score, -1 if
    lower raises it. NaN metrics are skipped per row, never penalized.
    """
    ranks = pd.DataFrame(index=snapshot.index)

    for column, sign in score_weights.items():
        ranks[column] = (sign * snapshot[column]).rank(pct=True)

    return (ranks.mean(axis=1, skipna=True) * 100.0).round(1)


def passes(snapshot: pd.DataFrame, criteria: dict[str, float]) -> pd.Series:
    """True where a row satisfies every criterion; NaN metrics fail their check.

    Criterion keys name a metric column plus a ``_min``/``_max`` suffix, e.g.
    ``"roic_ttm_min": 0.15`` requires ``snapshot["roic_ttm"] >= 0.15``.
    """
    result = pd.Series(True, index=snapshot.index)

    for key, threshold in criteria.items():
        column, _, bound = key.rpartition("_")

        if not column or bound not in ("min", "max"):
            raise ValueError(f"criterion {key!r} must end in '_min' or '_max'")

        if bound == "min":
            result &= snapshot[column] >= threshold
        else:
            result &= snapshot[column] <= threshold

    return result
