"""Risk management for the CSF Champions live book.

Reads open positions from Alpaca and flags holdings that have given back too
much from their high-water mark. Measuring from cost alone is blind to a winner
round-tripping: a name up 80% that falls 40% off its high is still positive on
cost and would never alert.
"""

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from agent_harness.sinks import LogSink
from alpaca.common.enums import Sort
from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest
from lumibot.strategies import Strategy

from systematic_trading.data.repository import load_daily_prices
from systematic_trading.logging_setup import get_logger
from systematic_trading.strategies.csf_champions.agents.risk_manager.agent import (
    build_risk_manager,
)
from systematic_trading.strategies.csf_champions.agents.risk_manager.models import (
    MAX_ADD_AMOUNT,
    DrawdownDecision,
)
from systematic_trading.strategies.csf_champions.portfolio import Portfolio

log = get_logger(__name__)

DRAWDOWN_THRESHOLD_PCT = -25.0
DRAWDOWN_REVIEW_WINDOW_DAYS = 14
MAX_WORKERS = 5

# Fills pulled per symbol when dating the open position. Deep enough to reach
# past the last flat point for any position this strategy holds.
ENTRY_ORDER_LOOKUP_LIMIT = 500

# Fractional-share tolerance when matching accumulated fills to position size.
QTY_TOLERANCE = 1e-6

# One breach row: ticker, give-back %, unrealized pnl %, avg entry, calendar day.
DrawdownBreach = tuple[str, float, float, float, date]


#     ================================
# --> Helper funcs
#     ================================


def whole_share_qty(raw: float, *, cap: int | None = None) -> int:
    """Round a share count to a non-negative whole number.

    Optional ``cap`` clamps the result (e.g. never sell more than held).
    """
    qty = max(0, round(raw))

    if cap is not None:
        qty = min(qty, cap)

    return qty


def entry_date(api, symbol: str, position_qty: float) -> date | None:
    """Date the currently open position was opened, from Alpaca's fill history.

    Walks fills newest to oldest and returns the one where the running signed
    quantity first equals the open position, i.e. the most recent point the
    book was flat in this name. Returns None when no such point is found.
    """
    request = GetOrdersRequest(
        status=QueryOrderStatus.CLOSED,
        symbols=[symbol],
        limit=ENTRY_ORDER_LOOKUP_LIMIT,
        direction=Sort.DESC,
    )

    running = 0.0

    for order in api.get_orders(filter=request):
        if not order.filled_at or not order.filled_qty:
            continue

        # sell_short reaches the API as a plain sell, so side alone gives the sign.
        # OrderSide is an enum whose str() is "OrderSide.BUY" — read .value instead.
        side = str(getattr(order.side, "value", order.side)).lower()

        signed = float(order.filled_qty) * (1.0 if side == "buy" else -1.0)
        running += signed

        if abs(running - position_qty) < QTY_TOLERANCE:
            return order.filled_at.date()

    return None


def give_back_pct(
    symbol: str,
    opened_on: date,
    avg_entry: float,
    current_price: float,
    is_short: bool,
) -> float:
    """Percent the price has moved against the position from its best level since entry.

    The entry price joins the candidates as a floor, so a position never in
    profit reports its plain unrealized PnL and can only alert earlier, never
    later. Best is the highest price for a long, the lowest for a short.
    """
    history = load_daily_prices(symbols=[symbol], start=opened_on, columns=["date", "close"])

    prices = [*history["close"].astype(float), current_price, avg_entry]
    best = min(prices) if is_short else max(prices)

    return (-1.0 if is_short else 1.0) * (current_price - best) / best * 100.0


def _position_drawdown(api, position, ticker: str) -> tuple[float, float]:
    """Give-back and unrealized PnL for one position, both in percent.

    Falls back to unrealized PnL as the give-back when the open date cannot be
    resolved — a risk check must never silently skip a position.
    """
    pnl_pct = round(float(position.unrealized_plpc) * 100.0, 2)

    quantity = float(position.qty)
    opened_on = entry_date(api, ticker, quantity)

    if opened_on is None:
        log.warning("%s: no flat point in fill history — falling back to unrealized pnl", ticker)
        return pnl_pct, pnl_pct

    give_back = give_back_pct(
        symbol=ticker,
        opened_on=opened_on,
        avg_entry=float(position.avg_entry_price),
        current_price=float(position.current_price),
        is_short=quantity < 0,
    )

    return round(give_back, 2), pnl_pct


def check_for_drawdown_breaches(
    strategy: Strategy,
    portfolio: Portfolio,
    threshold_pct: float = DRAWDOWN_THRESHOLD_PCT,
) -> list[DrawdownBreach]:
    """
    Check if any names in the portfolio are below the drawdown threshold (-25% right now).
    Measured as give-back from the position's high-water mark, so a winner that
    round-trips is caught as well as one that never worked.
    Return a list of tuples containing the ticker, give-back percentage, unrealized pnl
    percentage, average entry price, and date of the breach.
    This will skip any tickers that have already been reviewed by the agent (still in cooldown dict in portfolio class).
    """
    api = strategy.broker.api
    positions = api.get_all_positions()
    as_of = strategy.get_datetime().date()
    breaches: list[DrawdownBreach] = []

    for position in positions:
        ticker = position.symbol

        # If already reviewed by the agent (still in cooldown), skip it
        if ticker in portfolio.drawdown_reviews:
            continue

        # Give-back from the high-water mark, with unrealized pnl kept as context
        give_back, pnl_pct = _position_drawdown(api, position, ticker)

        # if the give-back is under the threshold, add it to the breaches list
        if give_back < threshold_pct:
            avg_entry = float(position.avg_entry_price)
            breaches.append((ticker, give_back, pnl_pct, avg_entry, as_of))

    if breaches:
        log.info(
            "drawdown breaches (threshold %.1f%%): %s",
            threshold_pct,
            ", ".join(
                f"{ticker} give-back {give_back:.2f}% (pnl {pnl_pct:.2f}%, entry ${avg_entry:.2f})"
                for ticker, give_back, pnl_pct, avg_entry, _ in breaches
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

def submit_drawdown_orders(
    strategy: Strategy,
    orders: list[tuple[DrawdownBreach, DrawdownDecision]],
) -> tuple[list[tuple[str, int, str]], list[tuple[str, int, str]]]:
    """Submit market orders for prior-session drawdown decisions.

    Sells (trim / exit) go first so cash is free before any adds. Returns the
    sized ``(sells, buys)`` lists as ``(ticker, qty, label)`` tuples.
    """
    # Create empty lists to store the sell and buy orders 
    sells: list[tuple[str, int, str]] = []
    buys: list[tuple[str, int, str]] = []

    if not orders:
        log.info("no pending drawdown orders to submit")
        return sells, buys

    # Resolve whole-share quantities first; skip anything that cannot size cleanly.
    for _breach, decision in orders:
        ticker = decision.ticker.strip().upper()
        position = strategy.get_position(ticker)
        held = abs(float(position.quantity)) if position is not None else 0.0
        
        # Max whole shares we can sell without going short of a fractional remainder.
        held_whole = math.floor(held)

        # If the position is not open, skip the order
        if held <= 0 or held_whole <= 0:
            log.warning("%s: no open position — skipping %s", ticker, decision.action)
            continue

        # If the decision is to exit, sell the entire whole-share position
        if decision.action == "exit":
            qty = held_whole
            sells.append((ticker, qty, "exit"))
            continue

        if decision.action == "trim":
            # The amount is a percentage of the position size so it can't be
            # less than 0 or greater than 1
            if decision.amount is None or not (0.0 < decision.amount < 1.0):
                log.warning(
                    "%s: trim needs 0 < amount < 1, got %s — skipping",
                    ticker,
                    decision.amount,
                )
                continue

            # Round allocation to whole shares; never sell more than held.
            qty = whole_share_qty(held * decision.amount, cap=held_whole)

            if qty <= 0:
                log.warning("%s: trim sizes to zero whole shares — skipping", ticker)
                continue

            sells.append((ticker, qty, f"trim {decision.amount:.0%}"))
            continue

        if decision.action == "add":
            if decision.amount is None or not (0.0 < decision.amount <= MAX_ADD_AMOUNT):
                log.warning(
                    "%s: add needs 0 < amount <= %s, got %s — skipping",
                    ticker,
                    MAX_ADD_AMOUNT,
                    decision.amount,
                )
                continue

            # Round allocation to whole shares (same fraction-of-held sizing).
            qty = whole_share_qty(held * decision.amount)

            if qty <= 0:
                log.warning("%s: add sizes to zero whole shares — skipping", ticker)
                continue

            buys.append((ticker, qty, f"add {decision.amount:.0%}"))

    # Loop through the tuple of sells list and submit the orders to the broker
    for ticker, qty, label in sells:
        order = strategy.create_order(
            ticker,
            qty,
            "sell",
            order_type="market",
            time_in_force="day",
        )

        strategy.submit_order(order)

        log.info("%s: market sell %d shares (%s)", ticker, qty, label)

    for ticker, qty, label in buys:
        order = strategy.create_order(
            ticker,
            qty,
            "buy",
            order_type="market",
            time_in_force="day",
        )

        strategy.submit_order(order)

        log.info("%s: market buy %d shares (%s)", ticker, qty, label)

    log.info(
        "drawdown order submit complete: %d sell(s), %d buy(s)",
        len(sells),
        len(buys),
    )

    return sells, buys


def _deploy_single_drawdown_agent(
    breach: DrawdownBreach,
) -> tuple[DrawdownBreach, DrawdownDecision]:
    """Run a fresh risk-manager agent on one breach."""
    # Unpack the breach tuple into its components
    ticker, give_back, pnl_pct, avg_entry, as_of = breach

    # Create agent instance of risk mngr agent (has to be built first)
    agent = build_risk_manager()

    task = (
        f"Review drawdown on {ticker}: {give_back}% below its best close "
        f"since we opened it, unrealized pnl {pnl_pct}%, "
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
        futures = {
            pool.submit(_deploy_single_drawdown_agent, breach): breach for breach in breaches
        }

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

    # if there are no breaches, return an empty list
    if not breaches:
        return []

    # 2. run the agent on the freshly drawdown identified tickers
    results = review_drawdowns(breaches)

    # Create a list of tuples of the breaches and decisions that are trim, exit, or add
    orders = [
        (breach, decision) # Expression
        for breach, decision in results # Loop 
        if decision.action in {"trim", "exit", "add"} # Condition
    ]

    # 3. Record successful reviews into the 2-week cooldown window.
    # Only successes from review_drawdowns land here; failures stay eligible.
    for breach, _decision in results:
        ticker, give_back, _pnl_pct, _avg_entry, as_of = breach
        portfolio.drawdown_reviews[ticker] = (ticker, give_back, as_of)

    if results:
        log.info(
            "recorded %d drawdown review(s) (cooldown started): %s",
            len(results),
            ", ".join(breach[0] for breach, _ in results),
        )

    return orders
