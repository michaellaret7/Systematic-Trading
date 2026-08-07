"""Capital reallocator live-book inspection tools."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import yaml

from systematic_trading.strategies.csf_champions.agents.cptl_reallocator import tools
from systematic_trading.strategies.csf_champions.portfolio import ALLOCATION_CAP_PCT


# ====================================
# --> Helpers
# ====================================


def _position(
    symbol: str,
    quantity: float,
    *,
    market_value: float | None = None,
    current_price: float | None = None,
) -> SimpleNamespace:
    """Minimal stand-in for a Lumibot Position."""
    return SimpleNamespace(
        symbol=symbol,
        quantity=quantity,
        market_value=market_value,
        current_price=current_price,
    )


def _strategy(positions: list, portfolio_value: float = 100_000.0) -> SimpleNamespace:
    """Minimal stand-in for a Lumibot Strategy."""
    return SimpleNamespace(
        get_positions=lambda: positions,
        portfolio_value=portfolio_value,
    )


def _returns_frame(symbols: list[str], days: int = 80, seed: int = 0) -> pd.DataFrame:
    """Synthetic daily returns with enough history for fit metrics."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-01-01", periods=days, freq="B")

    data = {symbol: rng.normal(0.0, 0.01, size=days) for symbol in symbols}

    return pd.DataFrame(data, index=index)


# ====================================
# --> Live book
# ====================================


def test_view_live_book_empty() -> None:
    """Empty broker book reports no open positions."""
    result = tools.view_live_book(_strategy=_strategy([]))

    assert result == "portfolio is empty — no open positions"


def test_view_live_book_lists_weights_and_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live book shows weights, market values, and sector tags heaviest first."""
    monkeypatch.setattr(
        tools,
        "load_sector_tags",
        lambda: {
            "AAPL": {"sector": "Technology", "industry": "Consumer Electronics"},
            "XOM": {"sector": "Energy", "industry": "Oil & Gas"},
        },
    )

    strategy = _strategy(
        [
            _position("XOM", 100, market_value=10_000.0, current_price=100.0),
            _position("AAPL", 50, market_value=20_000.0, current_price=400.0),
        ]
    )

    result = tools.view_live_book(_strategy=strategy)

    assert "2 open position(s)" in result
    assert "invested 30.00%" in result
    assert "cash ~70.00%" in result
    # Heaviest first: AAPL 20% before XOM 10%.
    assert result.index("AAPL") < result.index("XOM")
    assert "Technology / Consumer Electronics" in result
    assert "Energy / Oil & Gas" in result
    assert "total invested weight: 30.00%" in result


def test_view_live_book_falls_back_to_qty_times_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When market_value is missing, weight uses qty × current_price."""
    monkeypatch.setattr(
        tools,
        "load_sector_tags",
        lambda: {"MSFT": {"sector": "Technology", "industry": "Software"}},
    )

    strategy = _strategy([_position("MSFT", 10, market_value=None, current_price=250.0)])

    result = tools.view_live_book(_strategy=strategy)

    assert "weight  2.50%" in result
    assert "mv $    2,500.00" in result


def test_view_sector_exposure_groups_by_sector_and_industry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sector/industry rollups show account and book share with tickers."""
    monkeypatch.setattr(
        tools,
        "load_sector_tags",
        lambda: {
            "AAPL": {"sector": "Technology", "industry": "Consumer Electronics"},
            "MSFT": {"sector": "Technology", "industry": "Software"},
            "XOM": {"sector": "Energy", "industry": "Oil & Gas"},
        },
    )

    strategy = _strategy(
        [
            _position("AAPL", 10, market_value=15_000.0, current_price=150.0),
            _position("MSFT", 10, market_value=10_000.0, current_price=100.0),
            _position("XOM", 10, market_value=5_000.0, current_price=50.0),
        ]
    )

    result = tools.view_sector_exposure(_strategy=strategy)

    assert "sector exposure (3 holdings, 30.00% of account)" in result
    assert "Technology" in result
    assert "25.00% of account" in result
    assert "industry exposure:" in result
    assert "Consumer Electronics" in result
    assert "Oil & Gas" in result


def test_view_live_book_rejects_non_positive_portfolio_value() -> None:
    """Zero portfolio value is an error, not an empty book."""
    result = tools.view_live_book(_strategy=_strategy([], portfolio_value=0.0))

    assert result.startswith("error:")


# ====================================
# --> Candidate fit
# ====================================


def test_get_candidate_fit_rejects_held_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Already-held tickers are not valid replacement candidates."""
    monkeypatch.setattr(
        tools,
        "load_sector_tags",
        lambda: {"AAPL": {"sector": "Technology", "industry": "Consumer Electronics"}},
    )

    strategy = _strategy([_position("AAPL", 10, market_value=5_000.0, current_price=500.0)])
    result = tools.get_candidate_fit("aapl", 1.0, _strategy=strategy)

    assert result.startswith("error:")
    assert "already held" in result


def test_get_candidate_fit_reports_vol_and_correlation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fit preview returns vol, correlation, and invested-weight what-if."""
    monkeypatch.setattr(
        tools,
        "load_sector_tags",
        lambda: {
            "AAPL": {"sector": "Technology", "industry": "Consumer Electronics"},
            "XOM": {"sector": "Energy", "industry": "Oil & Gas"},
        },
    )
    monkeypatch.setattr(tools, "daily_returns", lambda symbols: _returns_frame(symbols))

    strategy = _strategy([_position("AAPL", 10, market_value=20_000.0, current_price=200.0)])
    payload = yaml.safe_load(tools.get_candidate_fit("XOM", 2.0, _strategy=strategy))

    candidate = payload["candidate"]

    assert candidate["ticker"] == "XOM"
    assert candidate["side"] == "long"
    assert candidate["weight_pct"] == 2.0
    assert candidate["sector"] == "Energy"
    assert candidate["industry"] == "Oil & Gas"
    assert candidate["invested_weight_now_pct"] == 20.0
    assert candidate["invested_weight_with_candidate_pct"] == 22.0
    assert candidate["would_exceed_allocation_cap"] is False
    assert "portfolio_vol_now_pct" in candidate
    assert "portfolio_vol_with_candidate_pct" in candidate
    assert "max_correlation_vs_holding" in candidate
    assert "avg_correlation_vs_book" in candidate


def test_get_candidate_fit_flags_allocation_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adding on top of a near-full book flags the sleeve allocation cap."""
    monkeypatch.setattr(
        tools,
        "load_sector_tags",
        lambda: {
            "AAPL": {"sector": "Technology", "industry": "Consumer Electronics"},
            "XOM": {"sector": "Energy", "industry": "Oil & Gas"},
        },
    )
    monkeypatch.setattr(tools, "daily_returns", lambda symbols: _returns_frame(symbols))

    # 63% invested + 2% candidate → 65% > 64% cap.
    strategy = _strategy([_position("AAPL", 10, market_value=63_000.0, current_price=100.0)])
    payload = yaml.safe_load(tools.get_candidate_fit("XOM", 2.0, _strategy=strategy))

    assert payload["candidate"]["would_exceed_allocation_cap"] is True
    assert payload["candidate"]["invested_weight_with_candidate_pct"] > ALLOCATION_CAP_PCT


def test_get_candidate_fit_errors_on_thin_candidate_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Candidates without enough price history return an error string."""
    monkeypatch.setattr(
        tools,
        "load_sector_tags",
        lambda: {"XOM": {"sector": "Energy", "industry": "Oil & Gas"}},
    )
    monkeypatch.setattr(tools, "daily_returns", lambda symbols: pd.DataFrame())

    strategy = _strategy([])
    result = tools.get_candidate_fit("XOM", 1.0, _strategy=strategy)

    assert result.startswith("error:")
    assert "price history" in result
