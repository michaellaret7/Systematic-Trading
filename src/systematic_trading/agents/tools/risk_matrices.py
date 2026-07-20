"""Agent tools: correlation and covariance matrices from the S3 daily prices parquet.

Both tools pull the last year of daily closes for a set of tickers, align them
on common trading days, and compute their matrix over daily simple returns.
All parquet I/O goes through ``data.repository``. The lookback is wall-clock —
risk checks are a live-agent flow, never a backtest.
"""

from datetime import date, timedelta
from typing import Annotated

import pandas as pd
import yaml
from agent_harness.decorator import Param, agent_tool

from systematic_trading.data.repository import load_daily_prices

LOOKBACK_DAYS = 365
MIN_OBSERVATIONS = 20

#     ================================
# --> Helper funcs
#     ================================


def _daily_returns(tickers: list[str]) -> pd.DataFrame | str:
    """Aligned daily simple returns for the tickers, or an "error: ..." string.

    Returns a wide frame (dates x tickers) restricted to days on which every
    ticker traded, so both matrices are computed on one common sample.
    """
    symbols = sorted({ticker.strip().upper() for ticker in tickers if ticker.strip()})

    if len(symbols) < 2:
        return "error: provide at least two distinct tickers"

    start = date.today() - timedelta(days=LOOKBACK_DAYS)
    frame = load_daily_prices(symbols=symbols, start=start, columns=["symbol", "date", "close"])

    missing = sorted(set(symbols) - set(frame["symbol"].unique()))

    if missing:
        return f"error: no daily price data for ticker(s) {missing}; are the symbols correct?"

    closes = frame.pivot(index="date", columns="symbol", values="close").sort_index()
    returns = closes.dropna().pct_change().dropna()

    if len(returns) < MIN_OBSERVATIONS:
        return (
            f"error: only {len(returns)} overlapping trading days for {symbols} in the last "
            f"{LOOKBACK_DAYS} days; need at least {MIN_OBSERVATIONS} to compute a matrix"
        )

    return returns


class _FixedPointDumper(yaml.SafeDumper):
    """SafeDumper that renders floats fixed-point (0.000055, never 5.5e-05)."""


def _represent_float_fixed(dumper: yaml.SafeDumper, value: float) -> yaml.ScalarNode:
    text = f"{value:.10f}".rstrip("0")

    if text.endswith("."):
        text += "0"

    return dumper.represent_scalar("tag:yaml.org,2002:float", text)


_FixedPointDumper.add_representer(float, _represent_float_fixed)


def _matrix_payload(returns: pd.DataFrame, matrix: pd.DataFrame, decimals: int) -> str:
    """YAML payload: sample metadata plus the matrix as nested ticker mappings."""
    # The returns index is already date-sorted, so first/last bound the sample.
    dates = pd.DatetimeIndex(returns.index).strftime("%Y-%m-%d")

    payload = {
        "tickers": list(matrix.columns),
        "observations": len(returns),
        "start": str(dates[0]),
        "end": str(dates[-1]),
        "matrix": {
            row: {col: round(float(matrix.loc[row, col]), decimals) for col in matrix.columns}
            for row in matrix.index
        },
    }

    return yaml.dump(payload, Dumper=_FixedPointDumper, sort_keys=False, default_flow_style=False)


#     ================================
# --> Tools
#     ================================


@agent_tool(name="GetCorrelationMatrix", safe_parallel=True)
def get_correlation_matrix(
    tickers: Annotated[
        list[str],
        Param(
            description="Ticker symbols to correlate, e.g. ['AAPL', 'MSFT', 'NVDA']. At least two."
        ),
    ],
) -> str:
    """
    Compute the pairwise Pearson correlation matrix of daily returns for a set
    of tickers over the last year of daily closes. Returns YAML: sample
    metadata (tickers, observations, start, end) followed by a `matrix`
    mapping of ticker -> ticker -> correlation in [-1, 1].

    Use it to judge how much diversification a set of positions actually
    provides — highly correlated names concentrate risk even when the theses
    differ. Returns are aligned on days every ticker traded, so all pairs
    share one sample. Bad inputs or unknown tickers return an "error: ..."
    string.
    """
    returns = _daily_returns(tickers)

    if isinstance(returns, str):
        return returns

    return _matrix_payload(returns, returns.corr(), decimals=4)


@agent_tool(name="GetCovarianceMatrix", safe_parallel=True)
def get_covariance_matrix(
    tickers: Annotated[
        list[str],
        Param(description="Ticker symbols, e.g. ['AAPL', 'MSFT', 'NVDA']. At least two."),
    ],
) -> str:
    """
    Compute the pairwise covariance matrix of daily returns for a set of
    tickers over the last year of daily closes. Returns YAML: sample metadata
    (tickers, observations, start, end) followed by a `matrix` mapping of
    ticker -> ticker -> covariance of daily returns (variances on the
    diagonal). Multiply by 252 to annualize.

    Use it when position sizing needs magnitude, not just direction —
    covariance scales with each ticker's volatility, where correlation does
    not. Returns are aligned on days every ticker traded, so all pairs share
    one sample. Bad inputs or unknown tickers return an "error: ..." string.
    """
    returns = _daily_returns(tickers)

    if isinstance(returns, str):
        return returns

    return _matrix_payload(returns, returns.cov(), decimals=6)


if __name__ == "__main__":
    print(get_correlation_matrix(["AAPL", "MSFT", "NVDA", "TSLA", "META"]))
    print(get_covariance_matrix(["AAPL", "MSFT", "NVDA"]))
