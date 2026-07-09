"""Panel-agnostic machinery shared by every screener."""

from systematic_trading.screeners.shared.criteria import Criterion, normalize_criteria
from systematic_trading.screeners.shared.screen import (
    composite_score,
    drop_sectors,
    drop_stale_rows,
    latest_visible_snapshot,
    passes,
    run_screen,
)
from systematic_trading.screeners.shared.validation import require_columns, require_unique_keys

__all__ = [
    "Criterion",
    "composite_score",
    "drop_sectors",
    "drop_stale_rows",
    "latest_visible_snapshot",
    "normalize_criteria",
    "passes",
    "require_columns",
    "require_unique_keys",
    "run_screen",
]
