"""Risk management for the CSF Champions live book.

Reads open positions from Alpaca and flags holdings whose unrealized PnL has
breached the drawdown threshold.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from agent_harness.sinks import LogSink
from lumibot.strategies import Strategy

from systematic_trading.logging_setup import get_logger
from systematic_trading.strategies.csf_champions.agents.risk_manager.agent import (
    build_risk_manager,
)
from systematic_trading.strategies.csf_champions.agents.risk_manager.models import (
    DrawdownDecision,
)
from systematic_trading.strategies.csf_champions.portfolio import Portfolio

log = get_logger(__name__)

DRAWDOWN_THRESHOLD_PCT = -25.0
DRAWDOWN_REVIEW_WINDOW_DAYS = 14
MAX_WORKERS = 5

# One breach row: ticker, unrealized pnl %, avg entry, strategy calendar day.
DrawdownBreach = tuple[str, float, float, date]


#     ================================
# --> Helper funcs
#     ================================


def check_for_drawdown_breaches(
    strategy: Strategy,
    portfolio: Portfolio,
    threshold_pct: float = DRAWDOWN_THRESHOLD_PCT,
) -> list[DrawdownBreach]:
    """
    Check if any names in the portfolio are below the drawdown threshold.
    Return a list of tuples containing the ticker, pnl percentage, average entry price, and date of the breach.
    This will skip any tickers that have already been reviewed by the agent (still in cooldown dict in portfolio class).
    """
    positions = strategy.broker.api.get_all_positions()
    as_of = strategy.get_datetime().date()
    breaches: list[DrawdownBreach] = []

    for position in positions:
        ticker = position.symbol

        # If already reviewed by the agent (still in cooldown), skip it
        if ticker in portfolio.drawdown_reviews:
            continue

        # Calculate the PnL percentage
        pnl_pct = round(float(position.unrealized_plpc) * 100.0, 2)

        # if the PnL is under the threshold, add it to the breaches list
        if pnl_pct < threshold_pct:
            avg_entry = float(position.avg_entry_price)
            breaches.append((ticker, pnl_pct, avg_entry, as_of))

    if breaches:
        log.info(
            "drawdown breaches (threshold %.1f%%): %s",
            threshold_pct,
            ", ".join(
                f"{ticker} {pnl_pct:.2f}% (entry ${avg_entry:.2f})"
                for ticker, pnl_pct, avg_entry, _ in breaches
            ),
        )
    else:
        log.info("no new positions below drawdown threshold %.1f%%", threshold_pct)

    return breaches


def clear_expired_drawdown_reviews(
    strategy: Strategy,
    portfolio: Portfolio,
    window_days: int = DRAWDOWN_REVIEW_WINDOW_DAYS,
) -> list[str]:
    """
    Remove tickers from the drawdown_reviews dict if they are older than the review window.
    This means that the protected 2 week window has expired for the ticker and it can be reviewed again if still in a drawdown.
    Return the list of tickers that were removed from the drawdown_reviews dict.
    """
    today = strategy.get_datetime().date()
    cutoff = today - timedelta(days=window_days)
    stale: list[str] = []

    # Check if the review date is older than the cooldown window
    for ticker, (_, _, review_date) in portfolio.drawdown_reviews.items():
        if review_date < cutoff:
            stale.append(ticker)

    # Delete expired reviews so they can be reviewed again
    for ticker in stale:
        del portfolio.drawdown_reviews[ticker]

    # Log the expired reviews
    if stale:
        log.info(
            "cleared %d drawdown review(s) older than %d days: %s",
            len(stale),
            window_days,
            ", ".join(stale),
        )
    else:
        log.info("no drawdown reviews outside the %d-day cooldown", window_days)

    return stale


def record_drawdown_reviews(
    portfolio: Portfolio,
    breaches: list[DrawdownBreach],
) -> None:
    """Mark tickers as agent-reviewed and start their cooldown window.

    Call this only once the agent has completed for the given breaches. Until
    then those tickers stay eligible for ``check_for_drawdown_breaches``.
    """
    for ticker, pnl_pct, _avg_entry, as_of in breaches:
        portfolio.drawdown_reviews[ticker] = (ticker, pnl_pct, as_of)

    if breaches:
        log.info(
            "recorded %d drawdown review(s) (cooldown started): %s",
            len(breaches),
            ", ".join(ticker for ticker, *_ in breaches),
        )


def _review_one(breach: DrawdownBreach) -> tuple[DrawdownBreach, DrawdownDecision]:
    """Run a fresh risk-manager agent on one breach."""
    # Unpack the breach tuple into its components
    ticker, pnl_pct, avg_entry, as_of = breach

    # Create agent instance of risk mngr agent (has to be built first)
    agent = build_risk_manager()

    task = (
        f"Review drawdown on {ticker}: unrealized pnl {pnl_pct}%, "
        f"avg entry ${avg_entry:.2f}, as of {as_of.isoformat()}. "
        f"Return a decision: hold, trim, exit, or add, with a short reason. "
        f"If add or trim, specify the amount."
    )

    result = agent.run(task, sink=LogSink(f"risk_{ticker}"))

    if not isinstance(result, DrawdownDecision):
        raise TypeError(f"risk manager must return DrawdownDecision, got {type(result).__name__}")

    return breach, result


def review_drawdowns(
    breaches: list[DrawdownBreach],
) -> list[tuple[DrawdownBreach, DrawdownDecision]]:
    """Run the drawdown agent on breached tickers; return a decision per success."""
    # ingest the list of tickers passed from the check_for_drawdown_breaches function
    if not breaches:
        return []

    # Create agent instance of risk mngr agent (has to be built first)
    # spawn the num workers per agent (each agent reviews one ticker)
    log.info("reviewing %d drawdown breach(es) with %d workers", len(breaches), MAX_WORKERS)

    # Create an empty list to store the decisions
    results: list[tuple[DrawdownBreach, DrawdownDecision]] = []

    # once the agents are spawned, wait for them to finish
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_review_one, breach): breach for breach in breaches}

        for future in as_completed(futures):
            breach = futures[future]
            ticker = breach[0]

            try:
                # once the agents are finished, return the decisions
                results.append(future.result())
                log.info("%s drawdown review done", ticker)
            except Exception:
                log.exception("%s drawdown review failed — not recording", ticker)

    return results


# =========================================
# --> Main workflow function
# =========================================


def manage_drawdowns(
    strategy: Strategy,
    portfolio: Portfolio,
) -> list[tuple[DrawdownBreach, DrawdownDecision]]:
    """Review drawdowns, record successes, and return actionable order instructions."""

    # 1. check for drawdown breaches in the portfolio (broker api)
    breaches = check_for_drawdown_breaches(strategy, portfolio)

    if not breaches:
        return []

    # 2. run the agent on the freshly drawdown identified tickers
    results = review_drawdowns(breaches)

    # 2a. Once the agent is FINISHED running, add it to the drawdown_reviews dict
    # add the newly viewed drawdown tickers to the drawdown_reviews dict via the record_drawdown_reviews function
    completed = [breach for breach, _decision in results]
    orders = [
        (breach, decision)
        for breach, decision in results
        if decision.action in {"trim", "exit", "add"}
    ]

    record_drawdown_reviews(portfolio, completed)

    return orders
