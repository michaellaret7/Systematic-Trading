"""screener — one shared fundamentals panel, thin screeners on top.

Infra layer (``fundamentals/``): pull raw FMP statement parquets from S3,
compute every fundamental metric we care about, and write one wide panel
parquet — the single source of truth all fundamental screeners read from.
"""

from systematic_trading.screener.fundamentals.data import load_panel

__all__ = ["load_panel"]
