"""Fundamentals panel: S3 statement data in, one wide metrics parquet out.

``data`` holds the S3 I/O, ``metrics`` the metric-group functions, and
``build`` the end-to-end panel build. Future panel families (e.g. prices)
get sibling packages under ``screener``.
"""

from systematic_trading.screener.fundamentals.data import load_panel

__all__ = ["load_panel"]
