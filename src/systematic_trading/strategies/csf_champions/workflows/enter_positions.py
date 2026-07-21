"""Submit entry orders for the finalized CSF Champions draft portfolio.

Turns each draft holding into a whole-share marketable DAY limit order: sized
as the holding's weight of the current account value, priced at the last price
plus a small buffer but never above the analyst's max entry price. Orders go
through the strategy's broker connection, so the same call works identically
in backtest, paper, and live. Holdings that cannot be entered (no price, or a
target too small for one whole share) are logged and skipped, never retried.
"""

import math

from lumibot.strategies import Strategy

from systematic_trading.logging_setup import get_logger
from systematic_trading.strategies.csf_champions.portfolio import Holding, Portfolio

log = get_logger(__name__)

# Marketable buffer: the limit sits this % above the last price so the order
# fills immediately while still capping the worst acceptable fill.
LIMIT_BUFFER_PCT = 0.5


#     ================================
# --> Helper funcs
#     ================================


def entry_limit_price(last_price: float, holding: Holding) -> float:
    """Marketable limit for one entry, never above the analyst's max entry price."""
    marketable = last_price * (1 + LIMIT_BUFFER_PCT / 100)

    return round(min(marketable, holding.max_entry_price), 2)


def submit_entry(strategy: Strategy, holding: Holding, account_value: float) -> bool:
    """Size and submit one whole-share limit buy; True if an order went out.

    The share count divides the dollar target by the limit price (not the last
    price), so even a fill at the cap cannot overspend the holding's weight.
    """
    last_price = strategy.get_last_price(holding.ticker)

    if last_price is None:
        log.warning("%s: no price available — skipping entry", holding.ticker)
        return False

    limit_price = entry_limit_price(float(last_price), holding)

    if float(last_price) > holding.max_entry_price:
        log.warning(
            "%s: last price $%.2f is above max entry $%.2f — order may not fill",
            holding.ticker,
            float(last_price),
            holding.max_entry_price,
        )

    target_dollars = holding.weight_pct / 100 * account_value
    quantity = math.floor(target_dollars / limit_price)

    if quantity == 0:
        log.warning(
            "%s: target $%.2f buys zero whole shares at $%.2f — skipping",
            holding.ticker,
            target_dollars,
            limit_price,
        )
        return False

    # TODO: Add an update to the Portfolio object and the DynamoDB tables
    # Update the ideas table with order status and update the trade ledger table
    order = strategy.create_order(
        holding.ticker, quantity, "buy", limit_price=limit_price, time_in_force="day"
    )
    strategy.submit_order(order)

    log.info(
        "%s: buy %d @ limit $%.2f (target %.2f%% = $%.2f)",
        holding.ticker,
        quantity,
        limit_price,
        holding.weight_pct,
        target_dollars,
    )

    return True


def enter_positions(strategy: Strategy, portfolio: Portfolio) -> None:
    """Submit one whole-share limit buy per draft holding.

    Reads the finalized draft book and pushes it to the broker. This sleeve is
    long-only, so any non-long holding is skipped with a warning rather than
    submitted.
    """
    if not portfolio.holdings:
        log.warning("Draft portfolio is empty — nothing to submit")
        return

    account_value = float(strategy.portfolio_value)
    submitted = 0

    for holding in portfolio.holdings.values():
        if holding.side != "long":
            log.warning(
                "%s: skipping %s idea — this sleeve is long-only", holding.ticker, holding.side
            )
            continue

        if submit_entry(strategy, holding, account_value):
            submitted += 1

    log.info(
        "Entry submission complete: %d/%d holdings submitted", submitted, len(portfolio.holdings)
    )
