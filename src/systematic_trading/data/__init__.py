"""Data enrichment layer.

Alpaca (through the Lumibot broker) is the live/backtest *price* feed. This package
holds everything else — supplementary data (fundamentals, macro, alt-data) that we
call directly from strategy/agent logic — split into two layers:

- ``providers`` — vendor I/O, one subpackage per vendor. ``providers.fmp.client.FMPClient``
  is the stable-API REST client (historical prices at every FMP increment plus
  fundamentals); ``providers.fmp.backtesting.FMPDataBacktesting`` is a Lumibot backtesting data
  source serving FMP bars, as an alternative to ``AlpacaBacktesting``.
- ``repository`` — the stored datasets on S3 (statement parquets, the fundamentals
  panel, daily prices). The only code that knows where data lives; everything above
  reads/writes through it, and providers are called only by the push/build scripts
  that fill it.
"""
