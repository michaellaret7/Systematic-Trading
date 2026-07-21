"""Submit entry orders for the finalized CSF Champions draft portfolio.

Turns each draft holding into a whole-share marketable DAY limit order: sized
as the holding's weight of the current account value, priced at the quoted ask
plus a small buffer but never above the analyst's max entry price. The last
trade price is the fallback base when the quote is missing or looks like feed
flicker. Holdings that cannot be entered (no price, or a target too small for
one whole share) are logged and skipped, never retried.

In live/paper runs each submission is also recorded in the trade ledger with
its full target quantity, and the broker order id is mapped to the ledger row
so fill events can accumulate against it.
"""

import math

from lumibot.strategies import Strategy

from systematic_trading.data.repository import record_order, update_idea_status
from systematic_trading.domain.trades import TradeOrder
from systematic_trading.logging_setup import get_logger
from systematic_trading.strategies.csf_champions.portfolio import Holding, Portfolio

log = get_logger(__name__)

STRATEGY = "csf_champions"

# Marketable buffer: the limit sits this % above the base price so the order
# fills immediately while still capping the worst acceptable fill.
LIMIT_BUFFER_PCT = 0.5

# Ask sanity cap: an ask more than this % above the last trade is treated as
# feed flicker (thin IEX quote) and the last trade price is used instead.
MAX_ASK_PREMIUM_PCT = 2.0


#     ================================
# --> Helper funcs
#     ================================


def entry_base_price(strategy: Strategy, ticker: str) -> float | None:
    """Price to build the marketable limit from: the ask when sane, else last trade.

    The ask is what a buy must cross to fill immediately; the last trade price
    is the fallback when the quote is missing or implausibly far above it.
    Alpaca reports "no quote" as 0.0 rather than None, so any non-positive
    price is treated as missing.
    """
    ask = strategy.get_quote(ticker).ask
    last_price = strategy.get_last_price(ticker)

    if ask is not None and float(ask) <= 0:
        ask = None

    if last_price is not None and float(last_price) <= 0:
        last_price = None

    if ask is None:
        return float(last_price) if last_price is not None else None

    if last_price is not None and float(ask) > float(last_price) * (1 + MAX_ASK_PREMIUM_PCT / 100):
        log.warning(
            "%s: ask $%.2f is >%s%% above last trade $%.2f — using last trade",
            ticker,
            float(ask),
            MAX_ASK_PREMIUM_PCT,
            float(last_price),
        )
        return float(last_price)

    return float(ask)


def entry_limit_price(base_price: float, max_entry_price: float) -> float:
    """Marketable limit for one entry, never above the analyst's max entry price."""
    marketable = base_price * (1 + LIMIT_BUFFER_PCT / 100)

    return round(min(marketable, max_entry_price), 2)


def submit_entry(strategy: Strategy, holding: Holding, account_value: float) -> bool:
    """Size and submit one whole-share limit buy; True if an order went out.

    The share count divides the dollar target by the limit price (not the base
    price), so even a fill at the cap cannot overspend the holding's weight.
    """
    base_price = entry_base_price(strategy, holding.ticker)

    if base_price is None:
        log.warning("%s: no price available — skipping entry", holding.ticker)
        return False

    limit_price = entry_limit_price(base_price, holding.max_entry_price)

    # A non-positive limit can only come from bad data; never size against it.
    if limit_price <= 0:
        log.warning(
            "%s: computed limit price $%.2f is not positive — skipping entry",
            holding.ticker,
            limit_price,
        )
        return False

    if base_price > holding.max_entry_price:
        log.warning(
            "%s: base price $%.2f is above max entry $%.2f — order may not fill",
            holding.ticker,
            base_price,
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

    order = strategy.create_order(
        holding.ticker, 
        quantity, 
        "buy", 
        limit_price=limit_price, 
        time_in_force="day",
        order_id=order.identifier
    )

    strategy.submit_order(order)

    # Ledger writes are live/paper only; fills accumulate against this row via
    # the strategy's fill hooks, keyed through the order-id -> trade_id map.
    # This is where the order is recorded in the trade ledger and the idea status 
    # is updated to "executed"
    if not strategy.is_backtesting:
        trade_id = record_order(
            TradeOrder(
                strategy=STRATEGY,
                idea_id=holding.idea_id,
                symbol=holding.ticker,
                side="buy",
                target_quantity=quantity,
                limit_price=limit_price,
                max_entry_price=holding.max_entry_price,
                submitted_at=strategy.get_datetime(),
            )
        )
        strategy.order_trade_ids[order.identifier] = trade_id

        update_idea_status(STRATEGY, holding.idea_id, "executed")

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

    # This is where the orders are submitted to the broker from
    # They are pulled from the Portfolio() object populated by the agent
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
