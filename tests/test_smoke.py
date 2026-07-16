"""Smoke tests: confirm the infra layer imports and wires up.

These do NOT hit the network or place orders — they just prove the environment is
sound. Run with: uv run pytest
"""

from importlib.util import find_spec

import pytest


def test_lumibot_is_installed() -> None:
    """Confirm the dependency exists without initializing broker infrastructure."""
    assert find_spec("lumibot") is not None


def test_alpaca_config_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """Alpaca configuration preserves paper mode as the safe default."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")
    monkeypatch.setenv("ALPACA_PAPER", "true")

    from systematic_trading.config import alpaca_config

    cfg = alpaca_config()
    assert cfg["API_KEY"] == "test-key"
    assert cfg["PAPER"] is True
