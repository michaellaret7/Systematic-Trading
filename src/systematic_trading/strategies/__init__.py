"""Trading strategies.

Each strategy subclasses ``lumibot.strategies.Strategy``. The same class runs in
backtest, paper, and live — only the broker/data-source wiring in the runner
(``systematic_trading.live`` / ``systematic_trading.backtest``) changes.

``STRATEGIES`` is the registry the runners select from.
"""

from typing import Any

from systematic_trading.strategies.btc_ticker.strategy import BtcTicker
from systematic_trading.strategies.csf_champions.strategy import CsfChampions

StrategyType = type[Any]

STRATEGIES: dict[str, StrategyType] = {
    "csf_champions": CsfChampions,
    "btc_ticker": BtcTicker,
}

__all__ = ["STRATEGIES"]
