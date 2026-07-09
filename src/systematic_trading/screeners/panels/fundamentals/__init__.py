"""Fundamentals panel: point-in-time metrics from quarterly FMP statements."""

from systematic_trading.screeners.panels.fundamentals.constants import (
    MAX_STALENESS_DAYS,
    PANEL_KEY,
)
from systematic_trading.screeners.panels.fundamentals.panel import (
    build_panel,
    load_panel,
    panel_uri,
)

__all__ = [
    "MAX_STALENESS_DAYS",
    "PANEL_KEY",
    "build_panel",
    "load_panel",
    "panel_uri",
]
