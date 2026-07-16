"""Reusable fundamentals-panel construction, metrics, and screening mechanics.

Infra layer (``fundamentals/``): pull raw FMP statement parquets from the data
repository, compute every fundamental metric we care about, and write one wide
panel parquet — the single source of truth all fundamental screeners read from
(via ``systematic_trading.data.repository``). Strategy-specific screening policy
stays inside the owning strategy package.
"""
