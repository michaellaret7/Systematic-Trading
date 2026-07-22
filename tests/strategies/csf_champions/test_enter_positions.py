"""Entry pricing guards against the quote data Alpaca actually returns.

The numbers below are real observations from the 2026-07-22 paper run, where
the broker's single-venue (IEX) feed disagreed with the consolidated market in
both directions: stale last trades on thin names, and asks parked 13-15% above
the real price.
"""

from systematic_trading.strategies.csf_champions.workflows.enter_positions import (
    choose_base_price,
    entry_limit_price,
)


def test_sane_ask_is_used_directly() -> None:
    """A live ask close to the reference is the base price.

    CRUS on 2026-07-22: ask $139.40 against a $139.30 consolidated price.
    """
    assert choose_base_price(ask=139.40, anchor=139.30, ticker="CRUS") == 139.40


def test_anchor_quality_decides_the_outcome() -> None:
    """The same ask resolves differently depending on the anchor it is judged against.

    LAUR on 2026-07-22 is the regression this rewrite fixed. Its ask ($35.68)
    tracked the real $35.60 market, but the broker's single-venue last trade sat
    stale at $33.16 — so anchoring on that stale print rejected a good ask and
    priced the order 6% below the market, where it never filled.

    The guard itself was never wrong; it was being fed a bad anchor.
    """
    assert choose_base_price(ask=35.68, anchor=33.16, ticker="LAUR") == 33.16
    assert choose_base_price(ask=35.68, anchor=35.60, ticker="LAUR") == 35.68


def test_zero_ask_falls_back_to_reference() -> None:
    """Alpaca reports 'no quote' as ask=0.0 — must not become a $0 limit.

    VEON on 2026-07-22 had no IEX offer at all while trading near $53.86.
    """
    assert choose_base_price(ask=0.0, anchor=53.86, ticker="VEON") == 53.86


def test_flickery_ask_falls_back_to_reference() -> None:
    """An ask far above the consolidated price is treated as feed flicker.

    CBT on 2026-07-22: a $103.13 IEX ask while the stock traded at $90.04.
    """
    assert choose_base_price(ask=103.13, anchor=90.04, ticker="CBT") == 90.04


def test_no_usable_price_returns_none() -> None:
    """Zero or missing on both sources means no entry, not a bad number."""
    assert choose_base_price(ask=0.0, anchor=0.0, ticker="AAPL") is None
    assert choose_base_price(ask=None, anchor=None, ticker="AAPL") is None


def test_missing_reference_trusts_the_ask() -> None:
    """With no anchor to judge against, the ask is all we have.

    The limit is still capped at the analyst's max entry price downstream.
    """
    assert choose_base_price(ask=139.40, anchor=None, ticker="CRUS") == 139.40


def test_limit_price_is_capped_at_max_entry() -> None:
    """The marketable buffer never lifts the limit above the analyst's cap."""
    assert entry_limit_price(100.0, max_entry_price=100.2) == 100.2
    assert entry_limit_price(100.0, max_entry_price=220.0) == 100.5
