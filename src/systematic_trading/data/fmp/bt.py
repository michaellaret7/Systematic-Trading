"""FMP-backed Lumibot backtesting data source.

``FMPDataBacktesting`` subclasses Lumibot's ``PandasData`` and deliberately keeps
``SOURCE == "PANDAS"``: the BacktestingBroker's order-fill loop only recognizes a
hardcoded list of source names (YAHOO/ALPACA/CCXT/DATABENTO), and PANDAS is the
supported path for custom data. Everything else — clock advancement, look-ahead
guarding, bar slicing — is inherited.

All bars are fetched from FMP up front (one request-walk per symbol, split-adjusted),
cached as parquet under Lumibot's cache folder, and handed to ``PandasData``.

Usage:
    MyStrategy.run_backtest(
        FMPDataBacktesting,
        start,
        end,
        symbols=["AAPL", "MSFT"],
        timestep="day",  # or "hour" / "minute" — Lumibot Data supports only these
        warm_up_trading_days=MyStrategy.WARM_UP_TRADING_DAYS,
    )
"""

import datetime as dt
from pathlib import Path

import pandas as pd
from lumibot.constants import LUMIBOT_CACHE_FOLDER
from lumibot.data_sources import PandasData
from lumibot.entities import Asset, Data

from systematic_trading.data.fmp.live import FMPClient

# Lumibot's Data entity only accepts minute/hour/day; map the intraday ones to the
# matching FMP increment ("day" routes to the daily EOD endpoint instead).
TIMESTEP_TO_INTERVAL = {"minute": "1min", "hour": "1hour"}

CACHE_DIR = Path(LUMIBOT_CACHE_FOLDER) / "fmp"

# Trading days -> calendar days, padded for weekends and holidays.
WARM_UP_CALENDAR_RATIO = 1.6

# Same key PandasData assigns when no quote is given; passing it explicitly
# silences the per-symbol "Using USD as the quote" warning.
USD_QUOTE = Asset(symbol="USD", asset_type="forex")


#     ================================
# --> Helper funcs
#     ================================


def _fetch_bars(
    client: FMPClient, symbol: str, timestep: str, start: dt.date, end: dt.date
) -> pd.DataFrame:
    """Pull OHLCV bars from FMP at the increment matching the backtest timestep."""
    if timestep == "day":
        return client.daily_prices(symbol, start, end)

    return client.intraday_prices(symbol, TIMESTEP_TO_INTERVAL[timestep], start, end)


def _cached_bars(
    client: FMPClient,
    symbol: str,
    timestep: str,
    start: dt.date,
    end: dt.date,
    refresh: bool,
) -> pd.DataFrame:
    """Load bars from the parquet cache, fetching and caching on a miss."""
    cache_file = CACHE_DIR / f"{symbol}_{timestep}_{start}_{end}.parquet"

    if cache_file.exists() and not refresh:
        return pd.read_parquet(cache_file)

    df = _fetch_bars(client, symbol, timestep, start, end)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_file)

    return df


#     ================================
# --> Data source
#     ================================


class FMPDataBacktesting(PandasData):
    """Backtest on FMP historical prices for a fixed symbol universe."""

    def __init__(
        self,
        datetime_start: dt.datetime | None = None,
        datetime_end: dt.datetime | None = None,
        symbols: list[str] | None = None,
        timestep: str = "day",
        warm_up_trading_days: int = 0,
        refresh_cache: bool = False,
        api_key: str | None = None,
        pandas_data: object = None,  # ignored: run_backtest passes None; bars come from FMP
        **kwargs,
    ):
        if not symbols:
            raise ValueError(
                "FMPDataBacktesting needs symbols=[...]; pass them through run_backtest(**kwargs)."
            )

        if timestep not in ("minute", "hour", "day"):
            raise ValueError(f"timestep must be 'minute', 'hour', or 'day', not {timestep!r}.")

        client = FMPClient(api_key=api_key)

        # Preload history before the window so indicators are warm at the first iteration.
        warm_up_days = int(warm_up_trading_days * WARM_UP_CALENDAR_RATIO) + 5
        fetch_start = datetime_start.date() - dt.timedelta(days=warm_up_days)

        # Lumibot values the final portfolio one bar past datetime_end; fetch a few
        # extra days (FMP returns only what exists) so that valuation isn't stale.
        fetch_end = datetime_end.date() + dt.timedelta(days=7)

        data = []

        for symbol in symbols:
            df = _cached_bars(client, symbol, timestep, fetch_start, fetch_end, refresh_cache)

            if df.empty:
                raise ValueError(
                    f"FMP returned no {timestep} bars for {symbol!r} "
                    f"between {fetch_start} and {fetch_end}."
                )

            data.append(Data(Asset(symbol), df, timestep=timestep, quote=USD_QUOTE))

        super().__init__(
            datetime_start=datetime_start,
            datetime_end=datetime_end,
            pandas_data=data,
            **kwargs,
        )
