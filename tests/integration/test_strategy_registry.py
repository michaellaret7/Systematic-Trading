"""Strategy registry and framework-import boundaries."""

import subprocess
import sys

from lumibot.strategies import Strategy

from systematic_trading.strategies import STRATEGIES


def test_registry_exposes_complete_strategies() -> None:
    """Every registered strategy is a runnable Lumibot strategy class."""
    assert "csf_champions" in STRATEGIES

    for name, strategy_class in STRATEGIES.items():
        assert issubclass(strategy_class, Strategy), name
        assert hasattr(strategy_class, "WARM_UP_TRADING_DAYS"), name


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
