"""Entry pricing guards against the quote data Alpaca actually returns."""

from types import SimpleNamespace

from systematic_trading.strategies.csf_champions.workflows.enter_positions import (
    entry_base_price,
    entry_limit_price,
)


class FakePriceStrategy:
    """Minimal stand-in exposing the two price calls entry pricing uses."""

    def __init__(self, ask: float | None, last: float | None) -> None:
        self._ask = ask
        self._last = last

    def get_quote(self, ticker: str) -> SimpleNamespace:
        return SimpleNamespace(ask=self._ask)

    def get_last_price(self, ticker: str) -> float | None:
        return self._last


def test_sane_ask_is_used_directly() -> None:
    """A live ask close to the last trade is the base price."""
    assert entry_base_price(FakePriceStrategy(ask=10.05, last=10.0), "AAPL") == 10.05


def test_zero_ask_falls_back_to_last_trade() -> None:
    """Alpaca reports 'no quote' as ask=0.0 — must not become a $0 limit."""
    assert entry_base_price(FakePriceStrategy(ask=0.0, last=23.5), "CMCSA") == 23.5


def test_flickery_ask_falls_back_to_last_trade() -> None:
    """An ask far above the last trade is treated as feed flicker."""
    assert entry_base_price(FakePriceStrategy(ask=10.5, last=10.0), "AAPL") == 10.0


def test_no_usable_price_returns_none() -> None:
    """Zero or missing on both sources means no entry, not a bad number."""
    assert entry_base_price(FakePriceStrategy(ask=0.0, last=0.0), "AAPL") is None
    assert entry_base_price(FakePriceStrategy(ask=None, last=None), "AAPL") is None


def test_limit_price_is_capped_at_max_entry() -> None:
    """The marketable buffer never lifts the limit above the analyst's cap."""
    assert entry_limit_price(100.0, max_entry_price=100.2) == 100.2
    assert entry_limit_price(100.0, max_entry_price=220.0) == 100.5
