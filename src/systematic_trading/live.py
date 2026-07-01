"""Live runner: trade any registered strategies on Alpaca.

Paper by default (``ALPACA_PAPER`` in .env controls it). All named strategies
share one broker connection and run in a single Trader until stopped with
Ctrl+C. Strategy names come from ``systematic_trading.strategies.STRATEGIES``.

Usage:
    uv run live
    uv run live sp500_momentum another_strategy
"""

from __future__ import annotations

import argparse

from lumibot.brokers import Alpaca
from lumibot.traders import Trader

from systematic_trading.config import alpaca_config, is_paper
from systematic_trading.logging_setup import configure_logging
from systematic_trading.strategies import STRATEGIES

DEFAULT_STRATEGIES = ["sp500_momentum"]

#     ================================
# --> Helper funcs
#     ================================


def parse_args() -> argparse.Namespace:
    """CLI: which registered strategies to run live."""
    parser = argparse.ArgumentParser(description="Trade registered strategies live on Alpaca.")

    parser.add_argument(
        "strategies",
        nargs="*",
        choices=sorted(STRATEGIES),
        help=f"registry name(s) of the strategies to run (default: {DEFAULT_STRATEGIES[0]})",
    )

    args = parser.parse_args()

    # argparse can't combine nargs="*" defaults with choices, so fall back here.
    args.strategies = args.strategies or DEFAULT_STRATEGIES

    return args


def main() -> None:
    args = parse_args()
    log = configure_logging()

    mode = "PAPER" if is_paper() else "LIVE"
    broker = Alpaca(alpaca_config())
    trader = Trader()

    for name in args.strategies:
        trader.add_strategy(STRATEGIES[name](broker=broker))
        log.info("starting | %s on Alpaca (%s)", name, mode)

    trader.run_all()


if __name__ == "__main__":
    main()
