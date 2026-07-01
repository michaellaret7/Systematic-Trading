"""Smoke tests: confirm the infra layer imports and wires up.

These do NOT hit the network or place orders — they just prove the environment is
sound. Run with: uv run pytest
"""

from __future__ import annotations


def test_lumibot_imports():
    from lumibot.brokers import Alpaca  # noqa: F401
    from lumibot.strategies import Strategy  # noqa: F401
    from lumibot.traders import Trader  # noqa: F401

def test_alpaca_config_shape(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")
    monkeypatch.setenv("ALPACA_PAPER", "true")

    from systematic_trading.config import alpaca_config

    cfg = alpaca_config()
    assert cfg["API_KEY"] == "test-key"
    assert cfg["PAPER"] is True
