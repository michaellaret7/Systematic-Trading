"""Risk management for the CSF Champions live book.

Reads open positions from Alpaca and flags holdings whose unrealized PnL has
breached the drawdown threshold.
"""

from datetime import date, timedelta

from lumibot.strategies import Strategy

from systematic_trading.logging_setup import get_logger
from systematic_trading.strategies.csf_champions.portfolio import Portfolio

log = get_logger(__name__)

DRAWDOWN_THRESHOLD_PCT = -25.0
DRAWDOWN_REVIEW_WINDOW_DAYS = 14

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
    """Return new drawdown breaches, excluding tickers already under revision.

    Pulls the live/paper book from Alpaca via ``strategy.broker.api``. PnL is
    Alpaca's ``unrealized_plpc`` as a percent (e.g. ``-18.5`` means -18.5%).
    Tickers already in ``portfolio.drawdown_revisions`` are omitted so the agent
    does not see duplicates inside the review window.

    Does not mutate ``drawdown_revisions`` — record only after the agent finishes.
    """
    positions = strategy.broker.api.get_all_positions()
    as_of = strategy.get_datetime().date()
    breaches: list[DrawdownBreach] = []

    for position in positions:
        ticker = position.symbol

        # If already reviewed (in the revisions dict), skip it
        if ticker in portfolio.drawdown_revisions:
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

def prune_drawdown_revisions(
    strategy: Strategy,
    portfolio: Portfolio,
    window_days: int = DRAWDOWN_REVIEW_WINDOW_DAYS,
) -> list[str]:
    """Drop drawdown revisions older than the rolling window ending today.

    Keeps entries whose revision date falls within the last ``window_days``
    calendar days (inclusive of the cutoff day). Returns the tickers removed so
    they can be re-reviewed if still in drawdown.
    """
    today = strategy.get_datetime().date()
    cutoff = today - timedelta(days=window_days)
    stale: list[str] = []

    # Check if the revision date is older than the cutoff window
    for ticker, (_, _, review_date) in portfolio.drawdown_revisions.items():
        if review_date < cutoff:
            stale.append(ticker)

    # Delete stale revisions from the portfolio so they can be reviewed again
    for ticker in stale:
        del portfolio.drawdown_revisions[ticker]

    # Log the stale revisions
    if stale:
        log.info(
            "pruned %d drawdown revision(s) older than %d days: %s",
            len(stale),
            window_days,
            ", ".join(stale),
        )
    else:
        log.info("no drawdown revisions outside the %d-day window", window_days)

    return stale

def record_drawdown_revisions(
    portfolio: Portfolio,
    breaches: list[DrawdownBreach],
) -> None:
    """Lock reviewed tickers into the revisions dict after the agent finishes.

    Call this only once the agent has completed for the given breaches. Until
    then those tickers stay eligible for ``check_for_drawdown_breaches``.
    """
    for ticker, pnl_pct, _avg_entry, as_of in breaches:
        portfolio.drawdown_revisions[ticker] = (ticker, pnl_pct, as_of)

    if breaches:
        log.info(
            "recorded %d drawdown revision(s): %s",
            len(breaches),
            ", ".join(ticker for ticker, *_ in breaches),
        )

def drawdown_agent(tickers: list[tuple], portfolio: Portfolio, breaches: list[DrawdownBreach]):
    """Run the drawdown agent on the drawdown breached tickers and return a decision for each one"""

    # ingest the list of tickers passed from the check_for_drawdown_breaches function
    # Create agent instance of risk mngr agent (has to be built first)
    # spawn the num workers per agent (each agent reviews one ticker)
    # once the agents are spawned, wait for them to finish
    # once the agents are finished, return the decisions
    # add the viewed drawdown tickers to the drawdown_revisions dict via the record_drawdown_revisions function

    pass


"""
the flow here should be:

1. check for drawdown breaches
  a. if there do not return tickers in the already reviewed dict
  b. if there are, return a tuple of (ticker, pnl_pct) [maybe add the fill price and date here]

2. run the agent on the drawdown breached tickers and return a decision for each one
  a. Once the agent is FINISHED running, add it to the drawdown_revisions dict

3. before market opens, drop all tickers that are expired from the 2 week review window so they can be reviewed again if they are still in a drawdown


"""
