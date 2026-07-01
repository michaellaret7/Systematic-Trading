"""Agentic decision layer.

Your LLM / tool-calling agents live here. They are plain Python — a strategy in
``strategies/`` calls into an agent during ``on_trading_iteration`` to produce
signals or sizing. Keep agents broker-agnostic so they run identically in backtest
and live.
"""
