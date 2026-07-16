"""Trading strategies.

Each strategy subclasses ``lumibot.strategies.Strategy``. The same class runs in
backtest, paper, and live — only the broker/data-source wiring in the runner
(``systematic_trading.live`` / ``systematic_trading.backtest``) changes.

``STRATEGIES`` is the registry the runners select from. It remains empty until
the first complete Lumibot strategy is ready for backtest and live execution.
"""

from typing import Any

StrategyType = type[Any]

STRATEGIES: dict[str, StrategyType] = {}

__all__ = ["STRATEGIES"]
