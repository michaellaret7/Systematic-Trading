"""Agent tool: is a drawdown the market, the sector, or the name itself?

Puts the stock, its sector, the broad market, and the macro tape in one window,
then says which of them explains the decline. Tradeable ETF benchmarks come from
FMP (the prices parquet holds only single names); peers, industry, and breadth
come from the parquet. The lookback is wall-clock — a live-agent flow, never a
backtest.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Annotated

import numpy as np
import pandas as pd
from agent_harness.decorator import Param, agent_tool

from systematic_trading.agents.shared_tools.utils.drawdown import drawdown_block
from systematic_trading.agents.shared_tools.utils.formatting import aligned_table, fmt
from systematic_trading.agents.shared_tools.utils.panel import wide_closes
from systematic_trading.data.providers.fmp import FMPClient
from systematic_trading.data.repository import load_sector_tags

# Calendar days pulled so the longest horizon still has a bar behind it.
LOOKBACK_DAYS = 420

# Horizons in trading bars, labelled the way an analyst says them.
HORIZONS = (("5d", 5), ("1m", 21), ("3m", 63), ("6m", 126), ("12m", 252))

# The window the verdict is read from — long enough to span a real drawdown.
VERDICT_BARS = 126

# Beta window in trading bars.
BETA_BARS = 252

# Benchmarks quoted beside the stock, grouped the way they are read.
BENCHMARK_GROUPS = (
    (
        "market",
        (("SPY", "S&P 500"), ("QQQ", "Nasdaq 100"), ("IWM", "small cap"), ("RSP", "S&P eq-wt")),
    ),
    ("style", (("IWF", "growth"), ("IWD", "value"))),
    (
        "macro",
        (("TLT", "20y treasury"), ("HYG", "high yield"), ("GLD", "gold"), ("UUP", "dollar")),
    ),
)

# FMP sector labels mapped to their SPDR sector ETF.
SECTOR_ETFS = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}

# Correlation below which a beta is too weak to attribute anything with.
MIN_BETA_CORRELATION = 0.3

# The verdict is read from the stock's gap to its sector-peer median, in points.
SINGLE_NAME_GAP_PCT = -15.0
SECTOR_FELL_PCT = -10.0

# A peer this far below its own trailing-year high counts toward sector breadth.
BREADTH_DRAWDOWN_PCT = -20.0
BREADTH_PEAK_BARS = 252

# Concurrent FMP fetches; one request covers one ETF's whole window.
MAX_FETCH_WORKERS = 8

#     ================================
# --> Helper funcs
#     ================================


def _etf_closes(symbols: list[str], start: date) -> pd.DataFrame:
    """Date x ETF close matrix from FMP, fetched concurrently."""
    client = FMPClient()
    today = date.today()
    series: dict[str, pd.Series] = {}

    with ThreadPoolExecutor(max_workers=MAX_FETCH_WORKERS) as pool:
        futures = {
            pool.submit(client.daily_prices, symbol, start, today): symbol for symbol in symbols
        }

        for future in as_completed(futures):
            symbol = futures[future]

            try:
                frame = future.result()
            except Exception:
                continue

            if frame.empty:
                continue

            closes = frame["close"]

            # FMP stamps bars in Eastern time; drop to plain dates so the parquet aligns.
            closes.index = pd.DatetimeIndex(closes.index).tz_localize(None).normalize()

            series[symbol] = closes

    return pd.DataFrame(series).sort_index()


def _window_return(closes: pd.Series, bars: int) -> float:
    """Percent return over ``bars`` trading days, or NaN without enough history."""
    clean = closes.dropna()

    if len(clean) <= bars:
        return float("nan")

    return (float(clean.iloc[-1]) / float(clean.iloc[-1 - bars]) - 1.0) * 100.0


def _peer_returns(universe: pd.DataFrame, peers: list[str], bars: int) -> pd.Series:
    """Every sector peer's return over one horizon, missing history dropped."""
    members = [peer for peer in peers if peer in universe.columns]

    return pd.Series({peer: _window_return(universe[peer], bars) for peer in members}).dropna()


def _row(label: str, closes: pd.Series) -> list[str]:
    """One benchmark's return across every horizon."""
    return [label, *(fmt(_window_return(closes, bars)) for _, bars in HORIZONS)]


def _returns_table(
    stock: pd.Series,
    etfs: pd.DataFrame,
    sector_etf: str | None,
    universe: pd.DataFrame,
    peers: list[str],
) -> str:
    """The stock beside its peers, its sector ETF, the market, and the macro tape."""
    head: list[list[str]] = [
        ["", *(label for label, _ in HORIZONS)],
        _row("stock", stock),
        # The peer median is the benchmark that needs no model — just the group itself.
        [
            "sector peers",
            *(fmt(_peer_returns(universe, peers, bars).median()) for _, bars in HORIZONS),
        ],
    ]

    if sector_etf and sector_etf in etfs:
        head.append(_row(f"{sector_etf} sector ETF", etfs[sector_etf]))

    blocks = [aligned_table(head, label_width=18, cell_width=9)]

    for _name, members in BENCHMARK_GROUPS:
        rows = [
            _row(f"{symbol}  {label}", etfs[symbol]) for symbol, label in members if symbol in etfs
        ]

        if rows:
            blocks.append(aligned_table(rows, label_width=18, cell_width=9))

    return "\n\n".join(blocks)


def _beta_to_sector(stock: pd.Series, sector: pd.Series) -> tuple[float, float]:
    """Beta and correlation of the stock's daily returns to its sector ETF's."""
    paired = pd.concat([stock, sector], axis=1, keys=["stock", "sector"]).dropna()
    returns = paired.tail(BETA_BARS + 1).pct_change(fill_method=None).iloc[1:]

    if len(returns) < BETA_BARS // 4:
        return float("nan"), float("nan")

    stock_returns = returns["stock"].to_numpy(dtype=float)
    sector_returns = returns["sector"].to_numpy(dtype=float)

    variance = float(np.var(sector_returns, ddof=1))

    if not variance:
        return float("nan"), float("nan")

    beta = float(np.cov(stock_returns, sector_returns)[0, 1]) / variance

    return beta, float(np.corrcoef(stock_returns, sector_returns)[0, 1])


def _attribution_line(stock: pd.Series, etfs: pd.DataFrame, sector_etf: str | None) -> str:
    """One line splitting the 6m move into the beta-explained part and the residual."""
    if not sector_etf or sector_etf not in etfs:
        return "  no sector ETF mapped for this name"

    beta, correlation = _beta_to_sector(stock, etfs[sector_etf])

    if not np.isfinite(correlation) or abs(correlation) < MIN_BETA_CORRELATION:
        return (
            f"  beta to {sector_etf} {fmt(beta)} but correlation is only {fmt(correlation)}"
            f" — this beta explains nothing, read the peer comparison instead"
        )

    stock_return = _window_return(stock, VERDICT_BARS)
    explained = beta * _window_return(etfs[sector_etf], VERDICT_BARS)

    return (
        f"  beta to {sector_etf} {fmt(beta)} (correlation {fmt(correlation)}): of the 6m"
        f" {fmt(stock_return)}%, sector beta explains {fmt(explained)}%,"
        f" {fmt(stock_return - explained)}% is idiosyncratic"
    )


def _verdict(stock: pd.Series, universe: pd.DataFrame, peers: list[str]) -> str:
    """Compare the stock to its sector peers over 6 months and call it.

    Deliberately model-free: it reads the gap to the peer median, so a weak or
    unstable beta cannot skew the answer.
    """
    stock_return = _window_return(stock, VERDICT_BARS)
    peer_returns = _peer_returns(universe, peers, VERDICT_BARS)

    if not np.isfinite(stock_return) or peer_returns.empty:
        return "  not enough history to compare against the sector"

    peer_median = float(peer_returns.median())
    gap = stock_return - peer_median
    percentile = float((peer_returns < stock_return).mean() * 100.0)

    if stock_return >= 0:
        call = f"no 6m decline to explain (stock {fmt(stock_return)}%)"
    elif gap <= SINGLE_NAME_GAP_PCT:
        call = "SINGLE-NAME — materially worse than the group it trades in"
    elif peer_median <= SECTOR_FELL_PCT:
        call = "SECTOR-DRIVEN — the whole group fell and this name is in line with it"
    elif gap >= 0:
        call = "IN LINE — the group is soft and this name is at or above its peer median"
    else:
        call = "MIXED — the sector is soft and the name is below its peer median"

    return (
        f"  6m: stock {fmt(stock_return)}% vs sector peer median {fmt(peer_median)}%"
        f" -> gap {fmt(gap)} points\n"
        f"  the stock sits at the {fmt(percentile, decimals=0)}th percentile"
        f" of {len(peer_returns)} sector peers\n"
        f"  verdict: {call}"
    )


def _leaderboard(etfs: pd.DataFrame, sector_etf: str | None) -> str:
    """Every sector ETF ranked over 3 months, so rotation is visible."""
    scored = [
        (_window_return(etfs[symbol], 63), symbol, name)
        for name, symbol in SECTOR_ETFS.items()
        if symbol in etfs
    ]
    scored = sorted((row for row in scored if np.isfinite(row[0])), reverse=True)

    rows = [
        [
            f"{rank}. {symbol} {name}",
            f"{fmt(value)}%{'  <-- this name' if symbol == sector_etf else ''}",
        ]
        for rank, (value, symbol, name) in enumerate(scored, start=1)
    ]

    return aligned_table(rows, label_width=32, cell_width=10)


def _breadth(peers: list[str], start: date) -> str:
    """How much of the sector is itself in drawdown from its own trailing-year high."""
    closes = wide_closes(start, symbols=peers)

    if closes.empty:
        return "  no peer price history"

    window = closes.tail(BREADTH_PEAK_BARS)
    drawdowns = ((window.iloc[-1] / window.max() - 1.0) * 100.0).dropna()

    if drawdowns.empty:
        return "  no peer price history"

    breached = int((drawdowns <= BREADTH_DRAWDOWN_PCT).sum())

    return (
        f"  {breached} of {len(drawdowns)} peers are {fmt(BREADTH_DRAWDOWN_PCT)}% or more"
        f" below their own 252d high ({fmt(breached / len(drawdowns) * 100.0, decimals=0)}%)\n"
        f"  peer median drawdown from own high {fmt(drawdowns.median())}%"
    )


def _industry_rank(symbol: str, tags: dict, closes: pd.DataFrame) -> str:
    """Where the stock sits among its own industry over 6 months."""
    industry = tags.get(symbol, {}).get("industry", "unknown")

    members = [
        peer
        for peer, tag in tags.items()
        if tag.get("industry") == industry and peer in closes.columns
    ]

    if len(members) < 3:
        return f"  industry {industry}: too few peers with price history"

    returns = pd.Series(
        {peer: _window_return(closes[peer], VERDICT_BARS) for peer in members}
    ).dropna()

    if symbol not in returns:
        return f"  industry {industry}: no 6m history for {symbol}"

    rank = int((returns > returns[symbol]).sum()) + 1

    return (
        f"  industry {industry} ({len(returns)} peers with 6m history)\n"
        f"  {symbol} 6m {fmt(returns[symbol])}% | industry median {fmt(returns.median())}%"
        f" | rank {rank} of {len(returns)}"
    )


#     ================================
# --> Tool
#     ================================


@agent_tool(name="GetMarketContext", safe_parallel=True)
def get_market_context(
    ticker: Annotated[str, Param(description="Ticker symbol, e.g. 'AAPL'.")],
) -> str:
    """
    Decide whether a ticker's decline is the market, its sector, or damage
    specific to the name. Reports where the stock sits against its trailing-year
    high and how it got there — a few gap-downs on heavy volume means there is
    an event to research, a slow bleed on ordinary volume usually means there is
    not — then compares it across 5d to 12m against its sector peers, its SPDR
    sector ETF, the broad market (SPY, QQQ, IWM, RSP), style (growth vs value)
    and the macro tape (treasuries, credit, gold, dollar).

    The verdict — sector-driven, single-name, in line, or mixed — comes from the
    stock's gap to its sector-peer median. Also ranks the eleven sector ETFs by
    3-month return so rotation is visible, places the stock inside its own
    industry, and counts how many sector peers are themselves 20% or more below
    their trailing-year high: wide breadth means the group is falling, narrow
    breadth points at the name. An unknown ticker returns an "error: ..." string.
    """
    symbol = ticker.strip().upper()
    start = date.today() - timedelta(days=LOOKBACK_DAYS)

    universe = wide_closes(start)

    if symbol not in universe.columns:
        return f"error: no daily price data for ticker {symbol!r}; is the symbol correct?"

    tags = load_sector_tags()
    sector = tags.get(symbol, {}).get("sector", "unknown")
    sector_etf = SECTOR_ETFS.get(sector)

    benchmarks = {symbol for _name, members in BENCHMARK_GROUPS for symbol, _ in members}
    etfs = _etf_closes(sorted(benchmarks | set(SECTOR_ETFS.values())), start)

    stock = universe[symbol].dropna()
    peers = [peer for peer, tag in tags.items() if tag.get("sector") == sector and peer != symbol]

    return (
        f"ticker: {symbol}\n"
        f"sector: {sector} ({sector_etf or 'no ETF mapping'})"
        f" | industry: {tags.get(symbol, {}).get('industry', 'unknown')}\n"
        f"as_of: {stock.index[-1].date()}\n"
        f"\n[drawdown]\n{drawdown_block(symbol, start)}\n"
        f"\n[returns] percent over each horizon\n"
        f"{_returns_table(stock, etfs, sector_etf, universe, peers)}\n"
        f"\n[attribution]\n{_attribution_line(stock, etfs, sector_etf)}\n"
        f"\n[call]\n{_verdict(stock, universe, peers)}\n"
        f"\n[sector rotation] sector ETFs ranked by 3m return\n{_leaderboard(etfs, sector_etf)}\n"
        f"\n[industry]\n{_industry_rank(symbol, tags, universe)}\n"
        f"\n[sector breadth]\n{_breadth(peers, start)}"
    )


if __name__ == "__main__":
    print(get_market_context(ticker="ADBE"))
