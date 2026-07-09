"""Screen machinery for screener.

Small synthetic panel with known dates and metrics; checks the point-in-time
cross-section, staleness drop, criteria gating (including NaN-fails), scoring
direction, and sector exclusion. No network, no S3.
"""

import numpy as np
import pandas as pd
import pytest

from systematic_trading.screener.fundamentals.screen import (
    composite_score,
    cross_section,
    drop_sectors,
    passes_gates,
    run_screen,
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


def test_passes_min_max_and_nan():
    snapshot = pd.DataFrame({"roic_ttm": [0.20, 0.10, np.nan], "debt": [1.0, 5.0, 1.0]})

    ok = passes_gates(snapshot, {"roic_ttm_min": 0.15, "debt_max": 2.0})

    assert ok.tolist() == [True, False, False]  # NaN fails its check


def test_passes_rejects_malformed_key():
    snapshot = pd.DataFrame({"roic_ttm": [0.2]})

    with pytest.raises(ValueError, match="_min' or '_max"):
        passes_gates(snapshot, {"roic_ttm": 0.15})


def test_composite_score_direction():
    snapshot = pd.DataFrame({"good": [1.0, 2.0, 3.0], "bad": [3.0, 2.0, 1.0]})

    score = composite_score(snapshot, {"good": 1, "bad": -1})

    # Row 2 is best on both metrics, row 0 worst on both.
    assert score.tolist() == sorted(score.tolist())


def test_drop_sectors():
    snapshot = pd.DataFrame({"symbol": ["A", "B", "C"], "sector": ["Utilities", "Tech", None]})

    kept = drop_sectors(snapshot, ("Utilities",))
    assert kept["symbol"].tolist() == ["B", "C"]  # missing sector stays by default

    strict = drop_sectors(snapshot, ("Utilities",), drop_missing_sector=True)
    assert strict["symbol"].tolist() == ["B"]


def test_run_screen_end_to_end():
    result = run_screen(
        make_panel(),
        criteria={"roic_ttm_min": 0.25},
        score_weights={"roic_ttm": 1},
        as_of=CUTOFF,
    )

    # Only GOOD clears 25% ROIC at the cutoff (NEW's 0.90 quarter isn't public yet).
    assert result["symbol"].tolist() == ["GOOD"]
    assert "score" in result.columns
