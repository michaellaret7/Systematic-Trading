"""Trading strategies.

Each strategy subclasses ``lumibot.strategies.Strategy``. The same class runs in
backtest, paper, and live — only the broker/data-source wiring in the runner
(``systematic_trading.live`` / ``systematic_trading.backtest``) changes.

``STRATEGIES`` is the registry the runners select from. To add a strategy:
subclass ``Strategy``, define ``WARM_UP_TRADING_DAYS`` on the class, and add it
to the dict here under the name you want to type on the command line.
"""

from __future__ import annotations

from lumibot.strategies import Strategy

