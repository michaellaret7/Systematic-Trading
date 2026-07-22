"""Submit entry orders for the finalized CSF Champions draft portfolio.

Turns each draft holding into a whole-share marketable DAY limit order: sized
as the holding's weight of the current account value, priced at the quoted ask
plus a small buffer so it crosses and fills. There is no valuation ceiling: the
book is meant to be fully invested, and the only price the strategy refuses is
one the data says is wrong. FMP's consolidated price is the fallback base when
the quote is missing or looks like feed flicker. Holdings that cannot be
entered (no price, or a target too small for one whole share) are logged and
skipped, never retried.

In live/paper runs each submission is also recorded in the trade ledger with
its full target quantity, and the broker order id is mapped to the ledger row
so fill events can accumulate against it.
"""

import math

import requests
from lumibot.strategies import Strategy

from systematic_trading.data.providers.fmp import FMPClient
from systematic_trading.data.repository import record_order, update_idea_status
from systematic_trading.domain.trades import TradeOrder
from systematic_trading.logging_setup import get_logger
from systematic_trading.strategies.csf_champions.portfolio import Holding, Portfolio

log = get_logger(__name__)

STRATEGY = "csf_champions"

# Marketable buffer: the limit sits this % above the base price so the order
# fills immediately while still capping the worst acceptable fill.
LIMIT_BUFFER_PCT = 0.5

# Ask sanity cap: an ask more than this % above the consolidated reference price
# is treated as feed flicker (thin IEX quote) and the reference is used instead.
# Measured live, the two populations separate cleanly: believable asks sit within
# ~1.7% of the reference, while flickering IEX asks sit 5-15% above it.
MAX_ASK_PREMIUM_PCT = 2.0


#     ================================
# --> Helper funcs
#     ================================


def consolidated_prices(tickers: list[str]) -> dict[str, float]:
    """Consolidated last trade per ticker from FMP, fetched in one call.

    The broker feed is single-venue (IEX), so its last trade can sit stale for
    an hour on a thin name while the stock trades elsewhere — which makes it
    useless for judging whether an ask is believable. FMP is delayed ~15 minutes
    but consolidated across venues, so it tracks the real price to well under 1%.

    A failure here is not fatal: callers fall back to the broker's own last
    trade, which is what this strategy used before.
    """
    try:
        return FMPClient().quotes(tickers)
    except (RuntimeError, requests.RequestException) as error:
        log.warning("FMP reference prices unavailable (%s) — using broker prices", error)
        return {}


def choose_base_price(ask: float | None, anchor: float | None, ticker: str) -> float | None:
    """Pick the price to build the marketable limit from: the ask when sane.

    The ask is what a buy must cross to fill immediately; the consolidated
    anchor is the fallback when the quote is missing or implausibly far above
    it. Alpaca reports "no quote" as 0.0 rather than None, so any non-positive
    price is treated as missing. ``ticker`` is used only for logging.
    """
    if ask is not None and float(ask) <= 0:
        ask = None

    if anchor is not None and float(anchor) <= 0:
        anchor = None

    if ask is None:
        return float(anchor) if anchor is not None else None

    if anchor is not None and float(ask) > float(anchor) * (1 + MAX_ASK_PREMIUM_PCT / 100):
        log.warning(
            "%s: ask $%.2f is >%s%% above reference $%.2f — using reference",
            ticker,
            float(ask),
            MAX_ASK_PREMIUM_PCT,
            float(anchor),
        )
        return float(anchor)

    return float(ask)


def entry_base_price(strategy: Strategy, ticker: str, anchor: float | None) -> float | None:
    """Resolve the broker's ask against a consolidated anchor into one base price.

    ``anchor`` comes from a batched `consolidated_prices` call; when it is missing
    (FMP unreachable, or no quote for this ticker) the broker's own last trade
    stands in, which is what this strategy used before.
    """
    ask = strategy.get_quote(ticker).ask

    if not anchor:
        anchor = strategy.get_last_price(ticker)

    return choose_base_price(ask, anchor, ticker)


def entry_limit_price(base_price: float) -> float:
    """Marketable limit for one entry: the base price plus the crossing buffer."""
    return round(base_price * (1 + LIMIT_BUFFER_PCT / 100), 2)


def submit_entry(
    strategy: Strategy, holding: Holding, account_value: float, anchor: float | None
) -> bool:
    """Size and submit one whole-share limit buy; True if an order went out.

    The share count divides the dollar target by the limit price (not the base
    price), so even a fill at the limit cannot overspend the holding's weight.
    """
    base_price = entry_base_price(strategy, holding.ticker, anchor)

    if base_price is None:
        log.warning("%s: no price available — skipping entry", holding.ticker)
        return False

    limit_price = entry_limit_price(base_price)

    # A non-positive limit can only come from bad data; never size against it.
    if limit_price <= 0:
        log.warning(
            "%s: computed limit price $%.2f is not positive — skipping entry",
            holding.ticker,
            limit_price,
        )
        return False

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

    # One batched call up front, so pricing the book costs a single round trip
    # rather than one per holding.
    anchors = consolidated_prices([holding.ticker for holding in portfolio.holdings.values()])

    # This is where the orders are submitted to the broker from
    # They are pulled from the Portfolio() object populated by the agent
    for holding in portfolio.holdings.values():
        if holding.side != "long":
            log.warning(
                "%s: skipping %s idea — this sleeve is long-only", holding.ticker, holding.side
            )
            continue

        if submit_entry(strategy, holding, account_value, anchors.get(holding.ticker)):
            submitted += 1

    log.info(
        "Entry submission complete: %d/%d holdings submitted", submitted, len(portfolio.holdings)
    )
