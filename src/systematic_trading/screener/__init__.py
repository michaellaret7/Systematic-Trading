"""screener — one shared fundamentals panel, thin screeners on top.

Infra layer (``fundamentals/``): pull raw FMP statement parquets from the data
repository, compute every fundamental metric we care about, and write one wide
panel parquet — the single source of truth all fundamental screeners read from
(via ``systematic_trading.data.repository``).
"""
