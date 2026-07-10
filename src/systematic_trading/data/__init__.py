"""Data enrichment layer.

Alpaca (through the Lumibot broker) is the live/backtest *price* feed. This package
holds adapters for supplementary data — fundamentals, macro, alt-data — that we call
directly from strategy/agent logic. Vendor adapters live under ``providers``:

- ``providers.fmp.live.FMPClient`` — stable-API REST client: historical prices at every
  FMP increment plus fundamentals (income statement, balance sheet, cash flow, ratios).
- ``providers.fmp.bt.FMPDataBacktesting`` — Lumibot backtesting data source that serves
  FMP bars, as an alternative to ``AlpacaBacktesting``.
"""
