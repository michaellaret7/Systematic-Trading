"""Cashflow Champions screener package."""

from systematic_trading.screeners.csf_champions.constants import (
    BALANCE_COLUMNS,
    CASHFLOW_COLUMNS,
    DEFAULT_CRITERIA,
    INCOME_COLUMNS,
    PANEL_KEY,
    SCORE_WEIGHTS,
)
from systematic_trading.screeners.csf_champions.panel import build_panel
from systematic_trading.screeners.csf_champions.screen import load_panel, panel_uri, screen

__all__ = [
    "BALANCE_COLUMNS",
    "CASHFLOW_COLUMNS",
    "DEFAULT_CRITERIA",
    "INCOME_COLUMNS",
    "PANEL_KEY",
    "SCORE_WEIGHTS",
    "build_panel",
    "load_panel",
    "panel_uri",
    "screen",
]
