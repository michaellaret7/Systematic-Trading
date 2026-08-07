"""Market-versus-sector-versus-single-name attribution for a ticker's drawdown."""

from datetime import date, timedelta

import pandas as pd

from systematic_trading.agents.shared_tools import market_context as ctx
from systematic_trading.agents.shared_tools.utils.panel import wide_closes


def _series(returns_pct: float, bars: int = ctx.VERDICT_BARS + 1) -> pd.Series:
    """A close series that ends exactly ``returns_pct`` above where it started."""
    start, end = 100.0, 100.0 * (1.0 + returns_pct / 100.0)

    return pd.Series([start] * (bars - 1) + [end])


def _universe(peer_returns: list[float]) -> tuple[pd.DataFrame, list[str]]:
    """A peer close matrix where each peer posts one of ``peer_returns``."""
    frame = pd.DataFrame({f"P{i}": _series(value) for i, value in enumerate(peer_returns)})

    return frame, list(frame.columns)


# ====================================
# --> Verdict rule
# ====================================


def test_verdict_calls_a_falling_group_sector_driven() -> None:
    """A name down with its group is not a single-name problem."""
    universe, peers = _universe([-18.0, -20.0, -22.0, -25.0, -19.0])

    call = ctx._verdict(_series(-21.0), universe, peers)

    assert "SECTOR-DRIVEN" in call


def test_verdict_calls_a_lone_faller_single_name() -> None:
    """A name far below a healthy group is name-specific."""
    universe, peers = _universe([5.0, 8.0, 12.0, 3.0, 10.0])

    call = ctx._verdict(_series(-20.0), universe, peers)

    assert "SINGLE-NAME" in call


def test_verdict_separates_in_line_from_below_median() -> None:
    """A soft group splits on which side of the peer median the name sits."""
    universe, peers = _universe([-4.0, -5.0, -6.0, -3.0, -5.0])

    assert "IN LINE" in ctx._verdict(_series(-4.0), universe, peers)
    assert "MIXED" in ctx._verdict(_series(-9.0), universe, peers)


def test_verdict_reports_no_decline_when_the_stock_is_up() -> None:
    """A profitable six months has no drawdown to attribute."""
    universe, peers = _universe([5.0, 8.0, 12.0])

    assert "no 6m decline" in ctx._verdict(_series(6.0), universe, peers)


def test_verdict_handles_missing_peers() -> None:
    """An unmapped or empty sector degrades to a plain message."""
    assert "not enough history" in ctx._verdict(_series(-20.0), pd.DataFrame(), [])


# ====================================
# --> Beta quality gate
# ====================================


def test_beta_reports_correlation_alongside_the_slope() -> None:
    """Beta ships with the correlation the caller needs to judge it."""
    sector = pd.Series(range(300)).astype(float) + 100.0
    stock = sector * 2.0

    beta, correlation = ctx._beta_to_sector(stock, sector)

    assert correlation > 0.99
    assert beta > 0.0


def test_beta_is_nan_without_enough_overlap() -> None:
    """Too little shared history yields no beta rather than a spurious one."""
    beta, correlation = ctx._beta_to_sector(_series(5.0, bars=10), _series(5.0, bars=10))

    assert pd.isna(beta) and pd.isna(correlation)


# ====================================
# --> Live data
# ====================================


def test_tool_runs_against_the_real_repository() -> None:
    """The whole tool renders every block for a real ticker."""
    output = ctx.get_market_context(ticker="ADBE")

    for block in (
        "[drawdown]",
        "[returns]",
        "[attribution]",
        "[call]",
        "[industry]",
        "[sector breadth]",
    ):
        assert block in output

    assert "error:" not in output


def test_unknown_ticker_returns_an_error_string() -> None:
    """An unrecognised symbol is reported, not raised."""
    assert ctx.get_market_context(ticker="ZZZZ").startswith("error:")


def test_breadth_counts_peers_against_their_own_highs() -> None:
    """Sector breadth is computed from real stored history."""
    tags = {"AAPL", "MSFT", "ADBE", "ORCL", "CRM"}
    start = date.today() - timedelta(days=ctx.LOOKBACK_DAYS)

    closes = wide_closes(start, symbols=sorted(tags))
    breadth = ctx._breadth(sorted(tags), start)

    assert not closes.empty
    assert "below their own 252d high" in breadth
