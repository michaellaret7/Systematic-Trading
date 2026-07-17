"""Agent tool: pull recent daily OHLCV bars from the S3 parquet repository.

Gives an agent the last two weeks of daily price/volume history for one
ticker so it can anchor valuation work on where the stock actually trades
today. All parquet I/O goes through ``data.repository``. The lookback is
wall-clock — price checks are a live-agent flow, never a backtest.
"""

from datetime import date, timedelta
from typing import Annotated

import yaml
from agent_harness.decorator import Param, agent_tool

from systematic_trading.data.repository import load_daily_prices

LOOKBACK_DAYS = 14


@agent_tool(name="GetRecentPrices", safe_parallel=True)
def get_recent_prices(
    ticker: Annotated[str, Param(description="Ticker symbol, e.g. 'AAPL'.")],
) -> str:
    """
    Pull the last two weeks of daily OHLCV bars (open, high, low, close,
    volume) for one ticker. Returns YAML tabular data: a `ticker` header key
    followed by a `rows` list, one mapping per trading day, oldest first.

    Use it to see the current price and how the stock has traded recently —
    e.g. to anchor valuation multiples on today's price rather than a stale
    fiscal-period-end price. An unknown ticker returns an "error: ..." string.
    """
    symbol = ticker.strip().upper()
    start = date.today() - timedelta(days=LOOKBACK_DAYS)

    frame = load_daily_prices(symbols=[symbol], start=start)

    if frame.empty:
        return f"error: no daily price data for ticker {symbol!r}; is the symbol correct?"

    frame = frame.sort_values("date")

    rows = [
        {
            "date": record["date"].strftime("%Y-%m-%d"),
            "open": round(float(record["open"]), 4),
            "high": round(float(record["high"]), 4),
            "low": round(float(record["low"]), 4),
            "close": round(float(record["close"]), 4),
            "volume": int(record["volume"]),
        }
        for record in frame.to_dict("records")
    ]

    payload = {"ticker": symbol, "rows": rows}

    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
