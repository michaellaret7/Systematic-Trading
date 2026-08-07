"""Agent tools for the CSF Champions capital reallocator.

Live book inspection against the broker: the reallocator redeploys capital
freed by drawdown exits into names that fit the current open book. The agent
returns structured picks; the workflow sizes them into buys — there is no
submit tool here.
"""

from __future__ import annotations

from typing import Annotated, Any

import pandas as pd
import yaml
from agent_harness.decorator import Param, agent_tool
from lumibot.strategies import Strategy

from systematic_trading.agents.shared_tools.correlations import MIN_OBSERVATIONS, daily_returns
from systematic_trading.data.repository import load_sector_tags
from systematic_trading.strategies.csf_champions.portfolio import ALLOCATION_CAP_PCT

TRADING_DAYS_PER_YEAR = 252

# ====================================
# --> Helper funcs
# ====================================


def _market_value(position: Any) -> float:
    """Position market value; fall back to qty × last price when unset."""
    raw = getattr(position, "market_value", None)

    if raw is not None:
        value = float(raw)

        if value != 0.0:
            return value

    price = getattr(position, "current_price", None)

    if price is None:
        return 0.0

    return float(position.quantity) * float(price)


def _position_rows(strategy: Strategy) -> list[dict[str, Any]]:
    """Open positions as plain rows with account weight and sector tags."""
    positions = strategy.get_positions()

    if not positions:
        return []

    account_value = float(strategy.portfolio_value)

    if account_value <= 0:
        return []

    tags = load_sector_tags()
    rows: list[dict[str, Any]] = []

    for position in positions:
        qty = float(position.quantity)

        if qty == 0:
            continue

        ticker = str(position.symbol).upper()
        market_value = _market_value(position)
        tag = tags.get(ticker, {"sector": "Unknown", "industry": "Unknown"})
        side = "long" if qty > 0 else "short"
        weight_pct = abs(market_value) / account_value * 100.0
        price = getattr(position, "current_price", None)

        rows.append(
            {
                "ticker": ticker,
                "side": side,
                "qty": qty,
                "price": float(price) if price is not None else None,
                "market_value": market_value,
                "weight_pct": weight_pct,
                "sector": tag["sector"],
                "industry": tag["industry"],
            }
        )

    rows.sort(key=lambda r: -r["weight_pct"])

    return rows


def _exposure_lines(
    groups: dict[str, list[dict[str, Any]]],
    total_weight: float,
) -> list[str]:
    """One line per group: combined weight as % of account and of book."""
    lines: list[str] = []

    for name, members in sorted(
        groups.items(), key=lambda kv: -sum(r["weight_pct"] for r in kv[1])
    ):
        weight = sum(r["weight_pct"] for r in members)
        tickers = ", ".join(sorted(r["ticker"] for r in members))
        book_share = (weight / total_weight * 100.0) if total_weight > 0 else 0.0

        lines.append(
            f"  {name:<28} {weight:>5.2f}% of account  {book_share:>5.1f}% of book  ({tickers})"
        )

    return lines


def _signed_weights(rows: list[dict[str, Any]]) -> pd.Series:
    """Account-level weight fraction per open position, negative for shorts."""
    return pd.Series(
        {
            r["ticker"]: r["weight_pct"] / 100.0 * (1.0 if r["side"] == "long" else -1.0)
            for r in rows
        }
    )


def _candidate_fit_block(
    usable: pd.DataFrame,
    cov: pd.DataFrame,
    base_weights: pd.Series,
    base_vol: float,
    symbol: str,
    weight_pct: float,
    sector: str,
    industry: str,
    invested_now_pct: float,
) -> dict[str, Any]:
    """What-if metrics for adding a long candidate at the given weight."""
    corr = usable.corr(min_periods=MIN_OBSERVATIONS)[symbol].drop(symbol).dropna()

    hypothetical = base_weights.copy()
    hypothetical[symbol] = weight_pct / 100.0

    aligned = hypothetical.reindex(cov.columns).fillna(0.0)
    variance = max(float(aligned @ cov @ aligned), 0.0)
    invested_with = invested_now_pct + weight_pct

    block: dict[str, Any] = {
        "ticker": symbol,
        "side": "long",
        "weight_pct": weight_pct,
        "sector": sector,
        "industry": industry,
        "annualized_vol_pct": round(
            float(usable[symbol].std()) * TRADING_DAYS_PER_YEAR**0.5 * 100, 1
        ),
        "portfolio_vol_now_pct": round(base_vol * 100, 1),
        "portfolio_vol_with_candidate_pct": round(variance**0.5 * 100, 1),
        "invested_weight_now_pct": round(invested_now_pct, 2),
        "invested_weight_with_candidate_pct": round(invested_with, 2),
        "would_exceed_allocation_cap": invested_with > ALLOCATION_CAP_PCT,
    }

    if not corr.empty:
        strongest = corr.abs().idxmax()

        block["max_correlation_vs_holding"] = f"{corr[strongest]:.2f} vs {strongest}"
        block["avg_correlation_vs_book"] = round(float(corr.mean()), 2)

    return block


# ====================================
# --> Inspection tools (read-only)
# ====================================


@agent_tool(name="ViewLiveBook", safe_parallel=True)
def view_live_book(_strategy: Strategy) -> str:
    """
    Show every open broker position: side, shares, last price, market value,
    weight as a percentage of account equity, and sector/industry. Heaviest
    weight first, with invested total and cash residual. This is live broker
    state, not the draft construction book.
    """
    rows = _position_rows(_strategy)

    if not rows:
        account_value = float(_strategy.portfolio_value)

        if account_value <= 0:
            return "error: portfolio value is not positive"

        return "portfolio is empty — no open positions"

    account_value = float(_strategy.portfolio_value)
    invested = sum(r["weight_pct"] for r in rows)
    cash_pct = max(0.0, 100.0 - invested)

    lines = [
        f"{len(rows)} open position(s) "
        f"(account ${account_value:,.2f}, invested {invested:.2f}%, cash ~{cash_pct:.2f}%):"
    ]

    for r in rows:
        price = f"${r['price']:,.2f}" if r["price"] is not None else "n/a"
        lines.append(
            f"  {r['ticker']:<6} {r['side']:<5}  "
            f"{r['qty']:>10.4g} sh  {price:>10}  "
            f"mv ${r['market_value']:>12,.2f}  "
            f"weight {r['weight_pct']:>5.2f}%  "
            f"{r['sector']} / {r['industry']}"
        )

    lines.append(f"total invested weight: {invested:.2f}%")

    return "\n".join(lines)


@agent_tool(name="ViewSectorExposure", safe_parallel=True)
def view_sector_exposure(_strategy: Strategy) -> str:
    """
    Break the live open book down by sector and by industry. Each row shows
    the group's combined weight as a percentage of the account and of the
    book, plus the tickers in it, heaviest first. Use it to spot concentration
    a replacement should diversify away from.
    """
    rows = _position_rows(_strategy)

    if not rows:
        return "portfolio is empty — no open positions"

    sectors: dict[str, list[dict[str, Any]]] = {}
    industries: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        sectors.setdefault(row["sector"], []).append(row)
        industries.setdefault(row["industry"], []).append(row)

    total = sum(r["weight_pct"] for r in rows)

    lines = [f"sector exposure ({len(rows)} holdings, {total:.2f}% of account):"]
    lines.extend(_exposure_lines(sectors, total))

    lines.append("industry exposure:")
    lines.extend(_exposure_lines(industries, total))

    return "\n".join(lines)


# ====================================
# --> Fit tools (read-only)
# ====================================


@agent_tool(name="GetCandidateFit", safe_parallel=True)
def get_candidate_fit(
    ticker: Annotated[
        str,
        Param(description="Ticker to evaluate as a hypothetical long addition."),
    ],
    weight_pct: Annotated[
        float,
        Param(
            description=(
                "Proposed account weight for the candidate (2.0 means 2%). "
                "Must be in the 0.5–3.0 position band."
            ),
            min_val=0.5,
            max_val=3.0,
        ),
    ],
    *,
    _strategy: Strategy,
) -> str:
    """
    What-if fit of one long candidate against the live open book. Uses a year
    of daily returns: candidate vol, strongest and average correlation to
    current holdings, portfolio vol before vs after the add, and invested
    weight before vs after (flagging if the sleeve allocation cap would be
    breached). Does not change the book or submit orders — preview only.
    """
    symbol = ticker.strip().upper()

    if not symbol:
        return "error: ticker must not be empty"

    account_value = float(_strategy.portfolio_value)

    if account_value <= 0:
        return "error: portfolio value is not positive"

    rows = _position_rows(_strategy)
    held = {r["ticker"] for r in rows}

    if symbol in held:
        return f"error: {symbol} is already held; its risk is already in the live book"

    tags = load_sector_tags()
    tag = tags.get(symbol, {"sector": "Unknown", "industry": "Unknown"})

    requested = sorted(held) + [symbol]
    returns = daily_returns(requested)

    thin = [t for t in requested if t not in returns or returns[t].count() < MIN_OBSERVATIONS]
    usable = returns.drop(columns=thin, errors="ignore")

    if symbol not in usable.columns:
        return (
            f"error: {symbol} has fewer than {MIN_OBSERVATIONS} days of price history "
            "— cannot trust fit metrics"
        )

    book_columns = [t for t in usable.columns if t in held]
    annual_cov = usable.cov(min_periods=MIN_OBSERVATIONS) * TRADING_DAYS_PER_YEAR

    if book_columns:
        weights = _signed_weights(rows).reindex(annual_cov.columns).fillna(0.0)
        variance = float(weights @ annual_cov @ weights)

        if variance <= 0:
            return "error: portfolio variance is not positive; price history is too sparse to trust"

        base_vol = variance**0.5
        base_weights = weights
    else:
        # Flat or thin book: treat current portfolio vol as zero.
        base_vol = 0.0
        base_weights = pd.Series(dtype=float)

    invested_now = sum(r["weight_pct"] for r in rows)
    candidate = _candidate_fit_block(
        usable,
        annual_cov,
        base_weights,
        base_vol,
        symbol,
        weight_pct,
        tag["sector"],
        tag["industry"],
        invested_now,
    )

    payload: dict[str, Any] = {"candidate": candidate}

    if thin:
        payload["excluded_insufficient_history"] = thin

    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
