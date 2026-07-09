"""Load and run the Junk Shorts screen — the Cashflow Champions inverse.

Reads the same fundamentals panel; only the opinions differ. ``score`` here is a
junk score: 100 is the most shortable company in the cross-section, not the best.
"""

from __future__ import annotations

import pandas as pd

from systematic_trading.screeners.junk_shorts.constants import (
    DEFAULT_CRITERIA,
    EXCLUDED_SECTORS,
    SCORE_WEIGHTS,
)
from systematic_trading.screeners.panels.fundamentals import MAX_STALENESS_DAYS, load_panel
from systematic_trading.screeners.shared import run_screen


def screen(
    panel: pd.DataFrame | None = None,
    as_of: pd.Timestamp | str | None = None,
    criteria: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Return Junk Shorts visible at ``as_of``, worst first by junk score."""
    panel = load_panel() if panel is None else panel
    criteria = {**DEFAULT_CRITERIA, **(criteria or {})}

    return run_screen(
        panel,
        as_of=as_of,
        criteria=criteria,
        score_weights=SCORE_WEIGHTS,
        max_staleness_days=MAX_STALENESS_DAYS,
        excluded_sectors=EXCLUDED_SECTORS,
        drop_missing_sector=True,
    )


if __name__ == "__main__":
    panel = load_panel()

    shorts = screen(panel, as_of="2025-03-01")
    print(shorts.head(20)[["symbol", "score"]])
