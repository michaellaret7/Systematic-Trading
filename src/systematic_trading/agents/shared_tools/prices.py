"""Agent tool: daily prices (and optional technicals) from the S3 parquet repository.

All parquet I/O goes through ``data.repository``. Lookbacks are wall-clock —
price checks are a live-agent flow, never a backtest.
"""

from datetime import date, timedelta
from typing import Annotated, Optional

import pandas as pd
from agent_harness.decorator import Param, agent_tool
from ta.momentum import ROCIndicator, RSIIndicator, StochasticOscillator
from ta.trend import ADXIndicator, MACD, SMAIndicator
from ta.volatility import AverageTrueRange, BollingerBands

from systematic_trading.agents.shared_tools.utils.formatting import day
from systematic_trading.data.repository import load_daily_prices

# Sessions returned when the caller does not ask for a longer window.
DEFAULT_SESSIONS = 14

# Warm-up bars loaded whenever technicals are requested so SMA-200 (and peers)
# are defined on every returned row; the response is still sliced to days_back.
WARMUP_BARS = 252

OHLCV_COLUMNS = ("date", "open", "high", "low", "close", "volume")

# Named column groups the agent can request. Order here is the column order
# appended after OHLCV.
TECHNICAL_GROUPS: dict[str, tuple[str, ...]] = {
    "momentum": ("rsi_14", "stoch_k_14", "stoch_d_14", "roc_12"),
    "trend": (
        "sma_20",
        "sma_50",
        "sma_200",
        "macd",
        "macd_signal",
        "macd_hist",
        "adx_14",
        "plus_di_14",
        "minus_di_14",
        "close_vs_sma_20_pct",
        "close_vs_sma_50_pct",
        "close_vs_sma_200_pct",
    ),
    "volatility": (
        "atr_14",
        "atr_14_pct",
        "bb_high_20",
        "bb_low_20",
        "bb_pct_b",
        "bb_width",
    ),
}

# Minimum bars of history before a group produces usable values.
_MIN_BARS: dict[str, int] = {
    "momentum": 15,
    "trend": 200,
    "volatility": 20,
}


#     ================================
# --> Helper funcs
#     ================================


def _start_for_sessions(sessions: int) -> date:
    """Calendar start that should cover roughly ``sessions`` trading days."""
    return date.today() - timedelta(days=int(sessions * 7 / 5) + 10)


def _technicals_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """OHLCV plus rolling momentum, trend, and volatility columns."""
    high = frame["high"]
    low = frame["low"]
    close = frame["close"]

    stoch = StochasticOscillator(high=high, low=low, close=close, window=14, smooth_window=3)
    macd = MACD(close=close)
    adx = ADXIndicator(high=high, low=low, close=close, window=14)
    bb = BollingerBands(close=close, window=20, window_dev=2)
    atr = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()

    out = frame[["date", "open", "high", "low", "close", "volume"]].copy()

    out["rsi_14"] = RSIIndicator(close=close, window=14).rsi()
    out["stoch_k_14"] = stoch.stoch()
    out["stoch_d_14"] = stoch.stoch_signal()
    out["roc_12"] = ROCIndicator(close=close, window=12).roc()

    out["sma_20"] = SMAIndicator(close=close, window=20).sma_indicator()
    out["sma_50"] = SMAIndicator(close=close, window=50).sma_indicator()
    out["sma_200"] = SMAIndicator(close=close, window=200).sma_indicator()
    out["macd"] = macd.macd()
    out["macd_signal"] = macd.macd_signal()
    out["macd_hist"] = macd.macd_diff()
    out["adx_14"] = adx.adx()
    out["plus_di_14"] = adx.adx_pos()
    out["minus_di_14"] = adx.adx_neg()
    out["close_vs_sma_20_pct"] = (close / out["sma_20"] - 1.0) * 100.0
    out["close_vs_sma_50_pct"] = (close / out["sma_50"] - 1.0) * 100.0
    out["close_vs_sma_200_pct"] = (close / out["sma_200"] - 1.0) * 100.0

    out["atr_14"] = atr
    out["atr_14_pct"] = atr / close * 100.0
    out["bb_high_20"] = bb.bollinger_hband()
    out["bb_low_20"] = bb.bollinger_lband()
    out["bb_pct_b"] = bb.bollinger_pband()
    out["bb_width"] = bb.bollinger_wband()

    return out


def _series_csv(frame: pd.DataFrame) -> str:
    """One header + one CSV row per day — denser and easier for an LLM than YAML maps."""
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out["volume"] = out["volume"].round().astype("Int64")

    for column in out.columns:
        if column in ("date", "volume"):
            continue

        out[column] = out[column].map(
            lambda value: f"{float(value):.2f}" if pd.notna(value) else ""
        )

    return out.to_csv(index=False)


def _resolve_groups(technicals: list[str] | None) -> tuple[str, ...] | str:
    """Normalize and validate technical group names, or return an error string."""
    if not technicals:
        return ()

    groups = tuple(name.strip().lower() for name in technicals if name and name.strip())
    unknown = sorted({name for name in groups if name not in TECHNICAL_GROUPS})

    if unknown:
        allowed = ", ".join(TECHNICAL_GROUPS)
        return f"error: unknown technicals {unknown}; choose from {allowed}"

    # Preserve caller order, drop duplicates.
    seen: set[str] = set()
    ordered: list[str] = []

    for name in groups:
        if name not in seen:
            seen.add(name)
            ordered.append(name)

    return tuple(ordered)


#     ================================
# --> Tools
#     ================================


@agent_tool(name="GetPrices", safe_parallel=True)
def get_prices(
    ticker: Annotated[str, Param(description="Ticker symbol, e.g. 'AAPL'.")],
    days_back: Annotated[
        int,
        Param(description="Number of trading sessions to return, ending at the latest bar."),
    ] = DEFAULT_SESSIONS,
    technicals: Annotated[
        Optional[list[str]],
        Param(
            description=(
                "Optional technical groups to append as columns after OHLCV: "
                "'momentum', 'trend', 'volatility'. Omit or pass [] for pure price."
            ),
        ),
    ] = None,
) -> str:
    """
    Daily OHLCV for one ticker, optionally widened with technical columns.

    ``days_back`` is how many sessions appear in the response. When technicals
    are requested, indicators are computed over a 252-bar warm-up window and
    the frame is sliced to those sessions so SMA-200 and peers are defined on
    every returned row. Empty/omitted technicals returns pure OHLCV.

    Returns a CSV table under a [bars] header, oldest first. An unknown ticker
    or bad argument returns an "error: ..." string.
    """
    symbol = ticker.strip().upper()

    if days_back < 1:
        return f"error: days_back must be >= 1, got {days_back}"

    groups = _resolve_groups(technicals)

    if isinstance(groups, str):
        return groups

    load_sessions = max(WARMUP_BARS, days_back) if groups else days_back
    frame = load_daily_prices(symbols=[symbol], start=_start_for_sessions(load_sessions))

    if frame.empty:
        return f"error: no daily price data for ticker {symbol!r}; is the symbol correct?"

    frame = frame.sort_values("date").reset_index(drop=True)

    if groups:
        needed = max(_MIN_BARS[group] for group in groups)

        if len(frame) < needed:
            return (
                f"error: only {len(frame)} daily bars for {symbol!r}; "
                f"need at least {needed} for technicals {list(groups)}"
            )

        frame = _technicals_frame(frame)
        columns = list(OHLCV_COLUMNS)

        for group in groups:
            columns.extend(TECHNICAL_GROUPS[group])
    else:
        columns = list(OHLCV_COLUMNS)

    bars = frame[columns].tail(days_back)
    groups_label = ",".join(groups) if groups else "none"

    return (
        f"ticker: {symbol}\n"
        f"as_of: {day(bars['date'].iloc[-1])}\n"
        f"technicals: {groups_label}\n"
        f"\n"
        f"[bars] last {len(bars)} sessions, oldest first\n"
        f"{_series_csv(bars)}"
    )


if __name__ == "__main__":
    print(get_prices(ticker="AAPL", days_back=10))
    print()
    print(get_prices(ticker="AAPL", days_back=30, technicals=["volatility","momentum","trend"]))
