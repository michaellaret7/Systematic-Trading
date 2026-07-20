"""Agent tool: pairwise price correlations and volatility for a set of tickers.

Computes daily-return correlations over the trailing year from the S3 prices
parquet, returned in an LLM-digestible form: the average pairwise correlation
and the most-correlated pairs — the full matrix only for small ticker sets,
where it is still readable. All parquet
I/O goes through ``data.repository``. The lookback is wall-clock — this is a
live-agent flow, never a backtest.
"""

from datetime import date, timedelta
from typing import Annotated

import pandas as pd
import yaml
from agent_harness.decorator import Param, agent_tool

from systematic_trading.data.repository import load_daily_prices

LOOKBACK_DAYS = 365
MIN_OBSERVATIONS = 60
DEFAULT_CORR_THRESHOLD = 0.4
MAX_PAIRS = 20
FULL_MATRIX_MAX_TICKERS = 10

#     ================================
# --> Helper funcs
#     ================================


def daily_returns(symbols: list[str]) -> pd.DataFrame:
    """Wide daily-return frame (date x symbol) over the trailing year.

    Public: the portfolio-risk tool builds on the same return matrix.
    """
    start = date.today() - timedelta(days=LOOKBACK_DAYS)

    prices = load_daily_prices(symbols=symbols, start=start, columns=["symbol", "date", "close"])

    if prices.empty:
        return pd.DataFrame()

    wide = prices.pivot_table(index="date", columns="symbol", values="close").sort_index()

    return wide.pct_change().iloc[1:]


def _top_pairs(matrix: pd.DataFrame, threshold: float) -> list[str]:
    """Every distinct pair at or above the threshold, strongest first."""
    pairs: list[tuple[float, str, str]] = []

    for i, left in enumerate(matrix.columns):
        for right in matrix.columns[i + 1 :]:
            value = matrix.at[left, right]

            if pd.notna(value) and abs(value) >= threshold:
                pairs.append((float(value), left, right))

    pairs.sort(key=lambda p: -abs(p[0]))

    return [f"{left}-{right}: {value:.2f}" for value, left, right in pairs]


#     ================================
# --> Tool
#     ================================


@agent_tool(name="GetPriceCorrelations", safe_parallel=True)
def get_price_correlations(
    tickers: Annotated[
        list[str],
        Param(description="Ticker symbols to analyze together, e.g. ['XOM', 'CVX', 'AAPL']."),
    ],
    threshold: Annotated[
        float,
        Param(
            description=(
                "Minimum |correlation| for a pair to be reported (default 0.4). Lower it "
                "to explore the book's broader co-movement structure; raise it to isolate "
                "near-duplicate bets."
            ),
            min_val=0.0,
            max_val=1.0,
        ),
    ] = DEFAULT_CORR_THRESHOLD,
) -> str:
    """
    Daily-return correlations for a set of tickers over the trailing year.
    Returns YAML: the `average_pairwise_correlation` and `correlated_pairs`
    at or above your threshold (strongest first, capped at 20 with an
    `pairs_omitted` count when more match) — plus the full
    `correlation_matrix` when 10 or fewer tickers are requested. Tickers
    with under ~3 months of price history are listed under
    `insufficient_history` and excluded.

    Use it to catch positions that are effectively the same bet: highly
    correlated names at full weight concentrate risk the sector breakdown
    alone won't show.
    """
    symbols = sorted({t.strip().upper() for t in tickers if t.strip()})

    if len(symbols) < 2:
        return "error: pass at least two tickers"

    returns = daily_returns(symbols)

    thin = [s for s in symbols if s not in returns or returns[s].count() < MIN_OBSERVATIONS]
    usable = returns.drop(columns=thin, errors="ignore")

    if len(usable.columns) < 2:
        return f"error: fewer than two tickers have {MIN_OBSERVATIONS}+ days of price history"

    matrix = usable.corr(min_periods=MIN_OBSERVATIONS)

    pairwise = matrix.stack()
    pairwise = pairwise[pairwise.index.get_level_values(0) != pairwise.index.get_level_values(1)]

    pairs = _top_pairs(matrix, threshold)

    payload: dict = {
        "lookback_days": LOOKBACK_DAYS,
        "pair_threshold": threshold,
        "average_pairwise_correlation": round(float(pairwise.mean()), 2),
        "correlated_pairs": pairs[:MAX_PAIRS] or "none at threshold",
    }

    if len(pairs) > MAX_PAIRS:
        payload["pairs_omitted"] = len(pairs) - MAX_PAIRS

    if len(matrix.columns) <= FULL_MATRIX_MAX_TICKERS:
        payload["correlation_matrix"] = {
            s: {o: round(float(matrix.at[s, o]), 2) for o in matrix.columns if o != s}
            for s in matrix.columns
        }

    if thin:
        payload["insufficient_history"] = thin

    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
