"""Live runner: trade any registered strategies on Alpaca.

Paper by default (``ALPACA_PAPER`` in .env controls it). All named strategies
share one broker connection and run in a single Trader until stopped with
Ctrl+C. Strategy names come from ``systematic_trading.strategies.STRATEGIES``.

A trailing ``local`` (default) or ``cloud`` word picks where it runs: ``local``
runs the Trader in this process, ``cloud`` launches one run-forever RunPod pod
per strategy and returns immediately.

Usage:
    uv run live <registered-strategy> [local|cloud]
"""

from __future__ import annotations

import argparse
import logging
import sys

from lumibot.brokers import Alpaca
from lumibot.traders import Trader

from systematic_trading.cloud.runpod import launch_strategy_pod
from systematic_trading.config import alpaca_config, is_paper
from systematic_trading.logging_setup import configure_logging
from systematic_trading.strategies import STRATEGIES

TARGETS = ("local", "cloud")

#     ================================
# --> Helper funcs
#     ================================

# Create runpod or Digital Ocean or Render pod using code and launch trading strategies from here.
# Create the infrastructure for this
# refer to launch trade ideas pod
# Another Note: create resuseable cloud deployment of strategies class


def parse_args() -> argparse.Namespace:
    """CLI: which registered strategies to run live, and where to run them.

    The optional trailing ``local``/``cloud`` word is split off before parsing:
    argparse cannot follow a ``nargs="+"`` list with an optional positional.
    """
    argv = sys.argv[1:]
    target = argv.pop() if argv and argv[-1] in TARGETS else "local"

    parser = argparse.ArgumentParser(
        description="Trade registered strategies live on Alpaca, locally or on RunPod.",
        epilog="Append 'local' (default) or 'cloud' after the strategy names.",
    )

    parser.add_argument(
        "strategies",
        nargs="+",
        choices=sorted(STRATEGIES),
        help="registry name(s) of the strategies to run",
    )

    args = parser.parse_args(argv)
    args.target = target

    return args


def run_cloud(strategy_names: list[str], log: logging.Logger) -> None:
    """Launch one run-forever RunPod pod per strategy and return."""
    for name in strategy_names:
        pod_id = launch_strategy_pod(name)

        log.info("launched | %s on RunPod pod %s", name, pod_id)


def main() -> None:
    args = parse_args()
    log = configure_logging()

    if args.target == "cloud":
        run_cloud(args.strategies, log)
        return

    mode = "PAPER" if is_paper() else "LIVE"
    broker = Alpaca(alpaca_config())
    trader = Trader()

    for name in args.strategies:
        trader.add_strategy(STRATEGIES[name](broker=broker))
        log.info("starting | %s on Alpaca (%s)", name, mode)

    trader.run_all()


if __name__ == "__main__":
    main()
