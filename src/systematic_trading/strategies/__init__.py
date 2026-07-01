"""Trading strategies.

Each strategy subclasses ``lumibot.strategies.Strategy``. The same class runs in
backtest, paper, and live — only the broker/data-source wiring in the runner script
changes. See ``example_buy_and_hold.py`` for the minimal shape.
"""
