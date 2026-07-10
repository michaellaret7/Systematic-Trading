"""Financial Modeling Prep adapters.

- ``live.FMPClient`` — stable-API REST client: historical prices at every FMP
  increment plus fundamentals (income statement, balance sheet, cash flow, ratios).
  Broker-agnostic; also feeds the backtesting source.
- ``bt.FMPDataBacktesting`` — Lumibot backtesting data source serving FMP bars.
"""

from systematic_trading.data.providers.fmp.bt import FMPDataBacktesting
from systematic_trading.data.providers.fmp.live import FMPClient

__all__ = ["FMPClient", "FMPDataBacktesting"]
