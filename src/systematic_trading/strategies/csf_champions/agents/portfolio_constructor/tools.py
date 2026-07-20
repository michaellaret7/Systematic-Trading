"""Agent tools for shaping the CSF Champions draft portfolio.

Each tool declares hidden ``_portfolio`` / ``_bench`` params bound at agent
construction via ``bind_tool``, so every call reads and mutates the same
in-memory state. Seeding is deterministic: ideas at or above the cut land in
the portfolio, the rest land on the bench. The agent can promote bench ideas
into the book, but it can never introduce a ticker that has no underlying
trade idea — AddPosition only accepts bench tickers.
"""

from typing import Annotated

import pandas as pd
import yaml
from agent_harness.decorator import Param, agent_tool

from systematic_trading.agents.tools.correlations import MIN_OBSERVATIONS, daily_returns
from systematic_trading.strategies.csf_champions.portfolio import (
    ALLOCATION_CAP_PCT,
    ALLOCATION_TARGET_PCT,
    MIN_SCORE,
    Holding,
    Portfolio,
)

TRADING_DAYS_PER_YEAR = 252

#     ================================
# --> Helper funcs
#     ================================


def _exposure_lines(groups: dict[str, list[Holding]], total_weight: float) -> list[str]:
    """One line per group: combined weight as % of account and % of book, plus tickers."""
    lines = []

    for name, members in sorted(groups.items(), key=lambda kv: -sum(h.weight_pct for h in kv[1])):
        weight = sum(h.weight_pct for h in members)
        tickers = ", ".join(sorted(h.ticker for h in members))

        lines.append(
            f"  {name:<28} {weight:>5.2f}% of account  "
            f"{weight / total_weight * 100:>5.1f}% of book  ({tickers})"
        )

    return lines


def _signed_weights(held: dict[str, Holding], tickers: list[str]) -> pd.Series:
    """Account-level weight fraction per ticker, negative for shorts."""
    return pd.Series(
        {t: held[t].weight_pct / 100 * (1 if held[t].side == "long" else -1) for t in tickers}
    )


def _resolve_candidate(
    symbol: str, weight_pct: float, portfolio: Portfolio, bench: dict[str, Holding]
) -> tuple[float, str] | str:
    """Weight and side for a what-if candidate, or an "error: ..." string."""
    if symbol in portfolio.holdings:
        return f"error: {symbol} is already held; its risk is in the positions table"

    on_bench = bench.get(symbol)

    if weight_pct <= 0 and on_bench is None:
        return f"error: {symbol} is not on the bench; pass candidate_weight_pct to profile it"

    weight = weight_pct if weight_pct > 0 else on_bench.weight_pct  # type: ignore[union-attr]
    side = on_bench.side if on_bench is not None else "long"

    return weight, side


def _candidate_block(
    usable: pd.DataFrame,
    cov: pd.DataFrame,
    base_weights: pd.Series,
    base_vol: float,
    symbol: str,
    weight_pct: float,
    side: str,
) -> dict:
    """What-if metrics for adding the candidate at the given weight."""
    corr = usable.corr(min_periods=MIN_OBSERVATIONS)[symbol].drop(symbol).dropna()

    hypothetical = base_weights.copy()
    hypothetical[symbol] = weight_pct / 100 * (1 if side == "long" else -1)

    aligned = hypothetical.reindex(cov.columns).fillna(0.0)
    variance = max(float(aligned @ cov @ aligned), 0.0)

    block = {
        "ticker": symbol,
        "side": side,
        "weight_pct": weight_pct,
        "annualized_vol_pct": round(float(usable[symbol].std()) * TRADING_DAYS_PER_YEAR**0.5 * 100, 1),
        "portfolio_vol_now_pct": round(base_vol * 100, 1),
        "portfolio_vol_with_candidate_pct": round(variance**0.5 * 100, 1),
    }

    if not corr.empty:
        strongest = corr.abs().idxmax()

        block["max_correlation_vs_holding"] = f"{corr[strongest]:.2f} vs {strongest}"
        block["avg_correlation_vs_book"] = round(float(corr.mean()), 2)

    return block


#     ================================
# --> Tools
#     ================================


@agent_tool(name="ViewPortfolio", safe_parallel=True)
def view_portfolio(_portfolio: Portfolio) -> str:
    """
    Show the current draft portfolio: every holding with its side, conviction
    score, weight, reference price, and max entry price, plus per-side weight
    totals and any positions already dropped this run.
    """
    return _portfolio.summary()


@agent_tool(name="ViewCandidateIdeas", safe_parallel=True)
def view_candidate_ideas(_bench: dict[str, Holding]) -> str:
    """
    List the pending trade ideas that scored below the automatic seeding cut —
    the bench the portfolio can be expanded from. One line per idea: the
    analyst's side, conviction score, proposed weight, sector/industry, and
    reference and max-entry prices, highest score first. Promotion removes an
    idea from the bench, so everything listed is still available to add.
    """
    if not _bench:
        return "no candidate ideas remain on the bench"

    lines = []

    for h in sorted(_bench.values(), key=lambda h: -h.score):
        lines.append(
            f"{h.ticker} ({h.side}, score {h.score:.1f}, proposed {h.weight_pct:.2f}%, "
            f"{h.sector} / {h.industry}, "
            f"ref ${h.reference_price:,.2f}, max entry ${h.max_entry_price:,.2f})"
        )

    return "\n".join(lines)


@agent_tool(name="ViewSectorExposure", safe_parallel=True)
def view_sector_exposure(_portfolio: Portfolio) -> str:
    """
    Break the current draft portfolio down by sector and by industry. Each row
    shows the group's combined weight as a percentage of the account and of
    the book, plus the tickers in it, heaviest first. Use it to spot
    concentration the book should diversify away — a sector carrying an
    outsized share of total weight is a single bet in disguise.
    """
    if not _portfolio.holdings:
        return "portfolio is empty"

    sectors: dict[str, list[Holding]] = {}
    industries: dict[str, list[Holding]] = {}

    for holding in _portfolio.holdings.values():
        sectors.setdefault(holding.sector, []).append(holding)
        industries.setdefault(holding.industry, []).append(holding)

    total = _portfolio.total_weight

    lines = [f"sector exposure ({len(_portfolio.holdings)} holdings, {total:.2f}% of account):"]
    lines.extend(_exposure_lines(sectors, total))

    lines.append("industry exposure:")
    lines.extend(_exposure_lines(industries, total))

    return "\n".join(lines)


@agent_tool(name="GetIdeaThesis", safe_parallel=True)
def get_idea_thesis(
    ticker: Annotated[str, Param(description="Ticker of a bench candidate or a current holding.")],
    _bench: dict[str, Holding],
    _portfolio: Portfolio,
) -> str:
    """
    The analyst's full investment thesis for one ticker — works for bench
    candidates and current holdings alike. Pull it for the few names you are
    actively weighing rather than for everything. Returns an "error: ..."
    string for unknown tickers.
    """
    symbol = ticker.strip().upper()

    holding = _portfolio.holdings.get(symbol) or _bench.get(symbol)

    if holding is None:
        return f"error: {symbol!r} is neither a holding nor a bench candidate"

    return f"{symbol} ({holding.side}, score {holding.score:.1f}): {holding.thesis}"


@agent_tool(name="AddPosition")
def add_position(
    ticker: Annotated[
        str, Param(description="Ticker of a candidate idea listed by ViewCandidateIdeas.")
    ],
    weight_pct: Annotated[
        float,
        Param(
            description=(
                "Portfolio weight percentage for the new position (2.0 means 2%), chosen "
                "by you — the analyst's proposed weight is a reference, not a mandate."
            ),
            min_val=0.5,
            max_val=3.0,
        ),
    ],
    _bench: dict[str, Holding],
    _portfolio: Portfolio,
) -> str:
    """
    Promote one bench idea into the draft portfolio at your chosen weight.
    Only tickers on the candidate bench can be added — there is no way to
    introduce a name without an underlying trade idea. Promotion removes the
    idea from the bench. Returns an "error: ..." string if the ticker is not
    on the bench (never an idea, already promoted, or dropped this run), or
    if the addition would push total allocation past the cap.
    """
    symbol = ticker.strip().upper()

    holding = _bench.get(symbol)

    if holding is None:
        return f"error: {symbol!r} is not on the candidate bench"

    projected = _portfolio.total_weight + weight_pct

    if projected > ALLOCATION_CAP_PCT:
        return (
            f"error: adding {symbol} at {weight_pct}% would take total allocation to "
            f"{projected:.2f}% — the portfolio allocation cap is {ALLOCATION_TARGET_PCT:.0f}%"
        )

    _bench.pop(symbol)

    holding.weight_pct = weight_pct

    _portfolio.add(holding)

    return f"{symbol} added to the portfolio at {weight_pct}%"


@agent_tool(name="SetPositionWeight")
def set_position_weight(
    ticker: Annotated[str, Param(description="Ticker of a holding already in the portfolio.")],
    weight_pct: Annotated[
        float,
        Param(
            description=(
                "New portfolio weight percentage for the position (2.0 means 2%). "
                "If the position deserves less than the 0.5 minimum, drop it instead."
            ),
            min_val=0.5,
            max_val=3.0,
        ),
    ],
    _portfolio: Portfolio,
) -> str:
    """
    Resize one existing holding to a new portfolio weight. Returns an
    "error: ..." string if the ticker is not in the portfolio.
    """
    symbol = ticker.strip().upper()

    if symbol not in _portfolio.holdings:
        return f"error: {symbol!r} is not in the portfolio"

    _portfolio.set_weight(symbol, weight_pct)

    return f"{symbol} weight set to {weight_pct}%"


@agent_tool(name="DropPosition")
def drop_position(
    ticker: Annotated[str, Param(description="Ticker of a holding already in the portfolio.")],
    reason: Annotated[
        str,
        Param(
            description=(
                "The specific reason the position is being removed — recorded so the "
                "underlying trade idea can be rejected downstream."
            )
        ),
    ],
    _portfolio: Portfolio,
) -> str:
    """
    Remove one holding from the draft portfolio. Only positions scoring below
    the conviction cut can be dropped — seeded high-conviction names are
    protected. The drop is permanent for this run — there is no way to re-add
    a ticker — so drop only with a clear reason. Returns an "error: ..."
    string if the ticker is not in the portfolio or is protected.
    """
    symbol = ticker.strip().upper()

    if symbol not in _portfolio.holdings:
        return f"error: {symbol!r} is not in the portfolio"

    if not reason.strip():
        return "error: reason must not be empty"

    score = _portfolio.holdings[symbol].score

    if score >= MIN_SCORE:
        return (
            f"error: {symbol} scored {score:.1f} — names at or above the {MIN_SCORE:.0f} "
            "conviction cut are core holdings and cannot be dropped"
        )

    _portfolio.drop(symbol, reason.strip())

    return f"{symbol} dropped from the portfolio"


@agent_tool(name="GetPortfolioRisk", safe_parallel=True)
def get_portfolio_risk(
    candidate_ticker: Annotated[
        str,
        Param(
            description=(
                "Optional what-if: a ticker to evaluate as a hypothetical addition. Adds "
                "a `candidate` block to the result — its vol, correlation to the book, "
                "and portfolio vol before vs after — without touching the portfolio."
            )
        ),
    ] = "",
    candidate_weight_pct: Annotated[
        float,
        Param(
            description=(
                "Weight for the what-if addition (defaults to the analyst's proposed "
                "weight for bench tickers)."
            ),
            min_val=0.0,
            max_val=3.0,
        ),
    ] = 0.0,
    *,
    _portfolio: Portfolio,
    _bench: dict[str, Holding],
) -> str:
    """
    Risk snapshot of the current draft book, computed from a year of daily
    returns. Returns YAML: the book's annualized volatility at the account
    level (cash outside the book dampens it), and per holding its weight,
    annualized volatility, and share of total portfolio risk, largest risk
    share first. Short positions enter with negative weight. Holdings with
    under ~3 months of price history are excluded and listed.

    Pass candidate_ticker to preview a promotion before committing to it: the
    `candidate` block shows the name's own vol, its strongest and average
    correlation to current holdings, and what the book's vol becomes if it is
    added — the bench and portfolio are left untouched.
    """
    held = _portfolio.holdings

    if not held:
        return "portfolio is empty"

    symbol = candidate_ticker.strip().upper()
    resolved: tuple[float, str] | str = (0.0, "")  # placeholder until a candidate is resolved

    if symbol:
        resolved = _resolve_candidate(symbol, candidate_weight_pct, _portfolio, _bench)

        if isinstance(resolved, str):
            return resolved

    requested = sorted(held) + ([symbol] if symbol else [])
    returns = daily_returns(requested)

    thin = [t for t in requested if t not in returns or returns[t].count() < MIN_OBSERVATIONS]
    usable = returns.drop(columns=thin, errors="ignore")

    book_columns = [t for t in usable.columns if t in held]

    if not book_columns:
        return f"error: no holding has {MIN_OBSERVATIONS}+ days of price history"

    annual_cov = usable.cov(min_periods=MIN_OBSERVATIONS) * TRADING_DAYS_PER_YEAR
    weights = _signed_weights(held, book_columns).reindex(annual_cov.columns).fillna(0.0)
    variance = float(weights @ annual_cov @ weights)

    if variance <= 0:
        return "error: portfolio variance is not positive; price history is too sparse to trust"

    # Component risk: weight x marginal covariance, normalized to sum to 100%.
    contributions = (weights * (annual_cov @ weights) / variance)[book_columns]
    single_vols = usable[book_columns].std() * TRADING_DAYS_PER_YEAR**0.5

    positions = {
        t: {
            "weight_pct": held[t].weight_pct,
            "annualized_vol_pct": round(float(single_vols[t]) * 100, 1),
            "risk_contribution_pct": round(float(contributions[t]) * 100, 1),
        }
        for t in sorted(book_columns, key=lambda t: -contributions[t])
    }

    payload: dict = {
        "portfolio_annualized_volatility_pct": round(variance**0.5 * 100, 1),
        "positions": positions,
    }

    if symbol and symbol in usable.columns:
        weight, side = resolved

        payload["candidate"] = _candidate_block(
            usable, annual_cov, weights, variance**0.5, symbol, float(weight), side
        )

    if thin:
        payload["excluded_insufficient_history"] = thin

    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
