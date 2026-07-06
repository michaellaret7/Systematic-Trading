"""Data enrichment layer.

Alpaca (through the Lumibot broker) is the live/backtest *price* feed. This package
holds adapters for supplementary data — fundamentals, macro, alt-data — that we call
directly from strategy/agent logic. FMP lives here:

- ``fmp.live.FMPClient`` — stable-API REST client: historical prices at every FMP
  increment plus fundamentals (income statement, balance sheet, cash flow, ratios).
- ``fmp.bt.FMPDataBacktesting`` — Lumibot backtesting data source that serves
  FMP bars, as an alternative to ``AlpacaBacktesting``.
"""
