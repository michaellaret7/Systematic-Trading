"""Fundamentals panel: repository statement data in, one wide metrics parquet out.

``metrics`` holds the metric-group functions and ``build`` the end-to-end panel
build; the S3 I/O lives in ``systematic_trading.data.repository``. Future panel
families (e.g. prices) get sibling packages under ``screener``.
"""
