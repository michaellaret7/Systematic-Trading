"""Fundamentals panel: repository statement data in, one wide metrics parquet out.

``metrics`` holds the metric-group functions, ``screen`` the reusable point-in-time
scoring mechanics, and ``build`` the end-to-end panel build. S3 I/O lives in
``systematic_trading.data.repository``; strategy policy stays with each strategy.
"""
