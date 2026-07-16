"""Backtest runner: run any registered strategies on Alpaca historical data.

Strategy names come from ``systematic_trading.strategies.STRATEGIES``; each one
backtests sequentially over the same window with the same budget. Daily bars —
each strategy's ``WARM_UP_TRADING_DAYS`` is preloaded so indicators are warm at
the first iteration. Outputs (stats CSV, trades, HTML tearsheet) land in the
``logs/`` directory.

Usage:
    uv run backtest <registered-strategy>
    uv run backtest <registered-strategy> --start 2024-01-01 --end 2024-12-31
"""

from __future__ import annotations

import argparse
from datetime import datetime

from lumibot.backtesting import AlpacaBacktesting

from systematic_trading.config import alpaca_config
from systematic_trading.logging_setup import configure_logging
from systematic_trading.strategies import STRATEGIES

DEFAULT_START = "2018-01-01"
DEFAULT_END = "2026-06-30"
DEFAULT_BUDGET = 1_000_000

#     ================================
# --> Helper funcs
#     ================================


def parse_args() -> argparse.Namespace:
    """CLI: which registered strategies to backtest, over what window, with what budget."""
    parser = argparse.ArgumentParser(
        description="Backtest registered strategies on Alpaca historical data."
    )

    parser.add_argument(
        "strategies",
        nargs="+",
        choices=sorted(STRATEGIES),
        help="registry name(s) of the strategies to backtest",
    )
    parser.add_argument(
        "--start",
        type=datetime.fromisoformat,
        default=DEFAULT_START,
        help=f"backtest start date, ISO format (default: {DEFAULT_START})",
    )
    parser.add_argument(
        "--end",
        type=datetime.fromisoformat,
        default=DEFAULT_END,
        help=f"backtest end date, ISO format (default: {DEFAULT_END})",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=DEFAULT_BUDGET,
        help=f"starting cash in dollars (default: {DEFAULT_BUDGET})",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    log = configure_logging()

    for name in args.strategies:
        strategy = STRATEGIES[name]

        log.info(
            "backtest | %s %s -> %s | $%s",
            name,
            args.start.date(),
            args.end.date(),
            f"{args.budget:,}",
        )

        strategy.run_backtest(
            AlpacaBacktesting,
            args.start,
            args.end,
            budget=args.budget,
            benchmark_asset="SPY",
            config=alpaca_config(),
            timestep="day",
            warm_up_trading_days=strategy.WARM_UP_TRADING_DAYS,
        )


if __name__ == "__main__":
    main()
