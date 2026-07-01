"""Thin Financial Modeling Prep (FMP) wrapper.

FMP is *not* a Lumibot data source — Alpaca remains the price feed for both
backtest and live. Use this for fundamentals / macro / alt-data enrichment that
your strategies and agents read alongside Alpaca prices.

Example (inside a Lumibot Strategy.on_trading_iteration):

    from systematic_trading.data.fmp import FMPClient

    fmp = FMPClient()
    price = self.get_last_price("AAPL")          # Alpaca, via Lumibot
    income = fmp.income_statement("AAPL", limit=4)  # FMP enrichment
"""

from __future__ import annotations

import fmpsdk

from systematic_trading.config import fmp_api_key


class FMPClient:
    """Convenience wrapper around ``fmpsdk`` that injects the API key for you.

    Every ``fmpsdk`` endpoint is available; the methods below are just the common
    ones. For anything not wrapped, call ``fmpsdk.<endpoint>(self.apikey, ...)``.
    """

    def __init__(self, apikey: str | None = None) -> None:
        self.apikey = apikey or fmp_api_key()

    def quote(self, symbol: str):
        return fmpsdk.quote(apikey=self.apikey, symbol=symbol)

    def income_statement(self, symbol: str, period: str = "annual", limit: int = 4):
        return fmpsdk.income_statement(
            apikey=self.apikey, symbol=symbol, period=period, limit=limit
        )

    def company_profile(self, symbol: str):
        return fmpsdk.company_profile(apikey=self.apikey, symbol=symbol)

    def key_metrics(self, symbol: str, period: str = "annual", limit: int = 4):
        return fmpsdk.key_metrics(
            apikey=self.apikey, symbol=symbol, period=period, limit=limit
        )
