"""Data enrichment layer.

Alpaca (through the Lumibot broker) is the live/backtest *price* feed. This package
holds adapters for supplementary data — fundamentals, macro, alt-data — that we call
directly from strategy/agent logic. FMP lives here.
"""
