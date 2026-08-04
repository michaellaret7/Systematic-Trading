"""Trading strategies.

Each strategy subclasses ``lumibot.strategies.Strategy``. The same class runs in
backtest, paper, and live — only the broker/data-source wiring in the runner
(``systematic_trading.live`` / ``systematic_trading.backtest``) changes.

``STRATEGIES`` is the registry the runners select from. Strategy classes are
imported only when a value is resolved (``STRATEGIES[name]``, ``.items()``,
``.values()``), so importing agents or other submodules under this package does
not pull in Lumibot.
"""

from collections.abc import Iterator, Mapping
from importlib import import_module
from typing import Any

StrategyType = type[Any]

# name → "module.path:ClassName" — classes load on first value access
_STRATEGY_PATHS: dict[str, str] = {
    "btc_ticker": "systematic_trading.strategies.btc_ticker.strategy:BtcTicker",
    "csf_champions": "systematic_trading.strategies.csf_champions.strategy:CsfChampions",
}


class StrategyRegistry(Mapping[str, StrategyType]):
    """Name → strategy class, imported only when a value is resolved."""

    def __init__(self, paths: dict[str, str]) -> None:
        self._paths = paths
        self._cache: dict[str, StrategyType] = {}

    def __getitem__(self, name: str) -> StrategyType:
        if name not in self._cache:
            if name not in self._paths:
                raise KeyError(name)

            module_path, class_name = self._paths[name].rsplit(":", 1)
            self._cache[name] = getattr(import_module(module_path), class_name)

        return self._cache[name]

    def __contains__(self, name: object) -> bool:
        # Mapping's default uses __getitem__, which would import the class.
        return name in self._paths

    def __iter__(self) -> Iterator[str]:
        return iter(self._paths)

    def __len__(self) -> int:
        return len(self._paths)


STRATEGIES: StrategyRegistry = StrategyRegistry(_STRATEGY_PATHS)

__all__ = ["STRATEGIES"]
