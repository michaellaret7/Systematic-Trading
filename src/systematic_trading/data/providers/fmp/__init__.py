"""Financial Modeling Prep REST client.

Import the Lumibot adapter explicitly from ``fmp.backtesting`` so data-ingestion
code does not initialize the trading framework.
"""

from systematic_trading.data.providers.fmp.client import FMPClient

__all__ = ["FMPClient"]
