"""Screen machinery for screener.

Small synthetic panel with known dates and metrics; checks the point-in-time
cross-section, staleness drop, scoring direction, weighted score groups, and
sector exclusion. No network, no S3.
"""

import numpy as np
import pandas as pd
import pytest

from systematic_trading.screener.fundamentals.screen import (
    composite_score,
    cross_section,
    drop_sectors,
    run_screen,
    sector_relative,
)

#     ================================
# --> Helper funcs
#     ================================


def make_panel() -> pd.DataFrame:
    """Three symbols, two quarters each; NEW's latest quarter files after the cutoff."""
    rows = [
        # symbol, fiscal quarter end, filed, roic
        ("GOOD", "2025-12-31", "2026-02-01", 0.30),
        ("GOOD", "2026-03-31", "2026-05-01", 0.35),
        ("NEW", "2025-12-31", "2026-02-10", 0.20),
        ("NEW", "2026-03-31", "2026-08-01", 0.90),  # not yet public at the cutoff
        ("DEAD", "2024-06-30", "2024-08-01", 0.50),  # stopped filing long ago
    ]

    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "date": pd.Timestamp(date),
                "filingDate": pd.Timestamp(filed),
                "roic_ttm": roic,
            }
            for symbol, date, filed, roic in rows
        ]
    )


CUTOFF = pd.Timestamp("2026-06-01")


#     ================================
# --> Tests
#     ================================


def test_cross_section_is_point_in_time():
    snapshot = cross_section(make_panel(), CUTOFF).set_index("symbol")

    # NEW's Q1-2026 row files in August; at the June cutoff only Q4-2025 is knowable.
    assert snapshot.loc["NEW", "roic_ttm"] == pytest.approx(0.20)
    assert snapshot.loc["GOOD", "roic_ttm"] == pytest.approx(0.35)


def test_cross_section_drops_stale_symbols():
    snapshot = cross_section(make_panel(), CUTOFF)

    assert "DEAD" not in snapshot["symbol"].values  # last quarter ~2 years old


def test_composite_score_direction():
    snapshot = pd.DataFrame({"good": [1.0, 2.0, 3.0], "bad": [3.0, 2.0, 1.0]})

    score = composite_score(snapshot, {"good": 1, "bad": -1})

    # Row 2 is best on both metrics, row 0 worst on both.
    assert score.tolist() == sorted(score.tolist())


def test_composite_score_uses_weight_magnitude():
    snapshot = pd.DataFrame({"primary": [1.0, 2.0], "secondary": [2.0, 1.0]})

    score = composite_score(snapshot, {"primary": 3, "secondary": 1})

    assert score.tolist() == [62.5, 87.5]


def test_run_screen_supports_complete_weighted_score_groups():
    panel = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "date": pd.to_datetime(["2026-03-31"] * 3),
            "filingDate": pd.to_datetime(["2026-05-01"] * 3),
            "quality": [3.0, 2.0, 1.0],
            "cash_yield": [3.0, 1.0, 2.0],
            "multiple": [1.0, 2.0, np.nan],
        }
    )

    result = run_screen(
        panel,
        as_of="2026-06-01",
        score_groups={
            "quality": {"quality": 1},
            "value": {"cash_yield": 3, "multiple": -1},
        },
        score_group_weights={"quality": 0.6, "value": 0.4},
        complete_score_groups=("value",),
    )

    assert result["symbol"].tolist() == ["A", "B", "C"]
    assert result["quality_metric_count"].tolist() == [1, 1, 1]
    assert result["value_metric_count"].tolist() == [2, 2, 1]
    assert result["value_metric_coverage"].tolist() == [1.0, 1.0, 0.5]
    assert result.loc[0, "score"] == pytest.approx(100.0)
    assert np.isnan(result.loc[2, "score"])


def test_drop_sectors():
    snapshot = pd.DataFrame({"symbol": ["A", "B", "C"], "sector": ["Utilities", "Tech", None]})

    kept = drop_sectors(snapshot, ("Utilities",))
    assert kept["symbol"].tolist() == ["B", "C"]  # missing sector stays by default

    strict = drop_sectors(snapshot, ("Utilities",), drop_missing_sector=True)
    assert strict["symbol"].tolist() == ["B"]


def test_sector_relative():
    snapshot = pd.DataFrame(
        {
            "sector": ["Tech", "Tech", "Energy", None],
            "roic_ttm": [0.30, 0.10, 0.05, 0.50],
        }
    )

    spread = sector_relative(snapshot, "roic_ttm")

    # Tech median 0.20, Energy is its own median; no sector -> no benchmark.
    assert spread.iloc[:3].tolist() == pytest.approx([0.10, -0.10, 0.0])
    assert np.isnan(spread.iloc[3])


def test_run_screen_returns_every_fresh_company():
    result = run_screen(
        make_panel(),
        score_weights={"roic_ttm": 1},
        as_of=CUTOFF,
    )

    # NEW's unpublished 0.90 quarter is excluded, but its latest public row remains ranked.
    assert result["symbol"].tolist() == ["GOOD", "NEW"]
    assert "score" in result.columns
