"""Panel-agnostic screen machinery: point-in-time snapshots and scoring.

Each screener module owns its score weights and sector exclusions; this module
owns the mechanics that are identical across screeners.

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
    score_weights: dict[str, float] | None = None,
    as_of: pd.Timestamp | str | None = None,
    excluded_sectors: tuple[str, ...] = (),
    drop_missing_sector: bool = False,
    sector_relative_columns: tuple[str, ...] = (),
    score_groups: dict[str, dict[str, float]] | None = None,
    score_group_weights: dict[str, float] | None = None,
    complete_score_groups: tuple[str, ...] = (),
) -> pd.DataFrame:
    """The standard screen pipeline over any metrics panel.

    Takes each symbol's latest row visible at ``as_of`` (defaults to the
    panel's newest filing), drops stale listings, optionally drops excluded
    sectors, scores the cross-section, and returns every row ranked by score.
    """

    # Build one fresh, eligible row per ticker.
    snapshot = _prepare_snapshot(panel, as_of, excluded_sectors, drop_missing_sector)

    # Add each requested metric's spread from its sector median.
    _add_sector_relative_columns(snapshot, sector_relative_columns)

    # Calculate the final composite or grouped score.
    _add_scores(
        snapshot,
        score_weights,
        score_groups,
        score_group_weights,
        complete_score_groups,
    )

    return snapshot.sort_values("score", ascending=False, ignore_index=True)


def _prepare_snapshot(
    panel: pd.DataFrame,
    as_of: pd.Timestamp | str | None,
    excluded_sectors: tuple[str, ...],
    drop_missing_sector: bool,
) -> pd.DataFrame:
    """Build the fresh point-in-time cross-section used for scoring."""
    cutoff = pd.Timestamp(as_of) if as_of is not None else panel["filingDate"].max()
    snapshot = cross_section(panel, cutoff)

    if excluded_sectors or drop_missing_sector:
        snapshot = drop_sectors(snapshot, excluded_sectors, drop_missing_sector)

    return snapshot


def _add_sector_relative_columns(
    snapshot: pd.DataFrame,
    columns: tuple[str, ...],
) -> None:
    """Add requested metrics as spreads from their sector medians."""
    for column in columns:
        snapshot[f"{column}_vs_sector"] = sector_relative(snapshot, column)


def _add_scores(
    snapshot: pd.DataFrame,
    score_weights: dict[str, float] | None,
    score_groups: dict[str, dict[str, float]] | None,
    score_group_weights: dict[str, float] | None,
    complete_score_groups: tuple[str, ...],
) -> None:
    """Add either one composite score or a weighted combination of score groups."""
    if score_groups is None:
        if score_weights is None:
            raise ValueError("score_weights or score_groups must be provided")

        snapshot["score"] = composite_score(snapshot, score_weights)
        return

    if score_weights is not None:
        raise ValueError("provide score_weights or score_groups, not both")
    if score_group_weights is None or set(score_group_weights) != set(score_groups):
        raise ValueError("score_group_weights must match score_groups")
    if any(weight <= 0 for weight in score_group_weights.values()):
        raise ValueError("score group weights must be positive")

    _add_group_scores(snapshot, score_groups, score_group_weights, complete_score_groups)


def _add_group_scores(
    snapshot: pd.DataFrame,
    score_groups: dict[str, dict[str, float]],
    group_weights: dict[str, float],
    complete_groups: tuple[str, ...],
) -> None:
    """Add each group score and combine them into the final weighted score."""
    for name, weights in score_groups.items():
        columns = list(weights)
        count_column = f"{name}_metric_count"
        coverage_column = f"{name}_metric_coverage"
        score_column = f"{name}_score"

        snapshot[count_column] = snapshot[columns].notna().sum(axis=1)
        snapshot[coverage_column] = snapshot[count_column] / len(columns)
        snapshot[score_column] = composite_score(snapshot, weights)

        if name in complete_groups:
            snapshot[score_column] = snapshot[score_column].where(snapshot[coverage_column] == 1.0)

    scores = pd.DataFrame(
        {name: snapshot[f"{name}_score"] for name in score_groups},
        index=snapshot.index,
    )

    weights = pd.Series(group_weights, dtype=float)
    weighted_scores = scores.mul(weights, axis="columns")

    snapshot["score"] = (
        weighted_scores.sum(axis=1, min_count=len(scores.columns)) / weights.sum()
    ).round(1)


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


def sector_relative(snapshot: pd.DataFrame, column: str) -> pd.Series:
    """Metric minus its sector median within this cross-section.

    Value creation is relative — ROIC mean-reverts toward the sector median, so
    the spread over that median is the durable part of the signal. Rows with no
    sector get NaN.
    """
    sector_median = snapshot.groupby("sector")[column].transform("median")

    return snapshot[column] - sector_median


def composite_score(snapshot: pd.DataFrame, score_weights: dict[str, float]) -> pd.Series:
    """Cross-sectional percentile-rank composite, 0-100.

    The sign of each weight sets whether higher or lower is better; its absolute
    value controls the metric's contribution. NaN metrics are skipped per row.
    """
    if not score_weights or any(weight == 0 for weight in score_weights.values()):
        raise ValueError("score weights must be non-zero")

    ranks = pd.DataFrame(index=snapshot.index)

    for column, weight in score_weights.items():
        direction = 1 if weight > 0 else -1
        ranks[column] = (direction * snapshot[column]).rank(pct=True)

    weights = pd.Series({column: abs(weight) for column, weight in score_weights.items()})
    weighted_sum = ranks.mul(weights, axis="columns").sum(axis=1, min_count=1)
    available_weight = ranks.notna().mul(weights, axis="columns").sum(axis=1)

    return (weighted_sum / available_weight * 100.0).round(1)
