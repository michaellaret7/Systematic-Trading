"""Strategy registry and framework-import boundaries."""

import subprocess
import sys

from systematic_trading.strategies import STRATEGIES


def test_registry_is_truthfully_empty_until_strategy_is_implemented() -> None:
    """No incomplete strategy is exposed to live or backtest runners."""
    assert STRATEGIES == {}


def test_fmp_client_import_does_not_initialize_lumibot() -> None:
    """The REST client remains independent from the trading framework."""
    command = (
        "import sys; "
        "from systematic_trading.data.providers.fmp import FMPClient; "
        "assert FMPClient; "
        "assert 'lumibot' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", command],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
