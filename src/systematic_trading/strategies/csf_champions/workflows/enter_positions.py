"""Submit market entry orders for the finalized CSF Champions portfolio.

Each holding is sized into whole shares from the broker's latest price and
submitted as a DAY market order. Live and paper orders are recorded before
submission so an immediate fill can always resolve its trade-ledger row.
"""

import math

from lumibot.strategies import Strategy

from systematic_trading.data.repository import record_order, update_idea_status
from systematic_trading.domain.trades import TradeOrder
from systematic_trading.logging_setup import get_logger
from systematic_trading.strategies.csf_champions.portfolio import Holding, Portfolio

log = get_logger(__name__)

STRATEGY = "csf_champions"


#     ================================
# --> Helper funcs
#     ================================


def entry_quantity(strategy: Strategy, holding: Holding, account_value: float) -> int:
    """Return the whole-share market quantity; zero means skip the holding."""
    last_price = strategy.get_last_price(holding.ticker)

    if last_price is None:
        log.warning("%s: no valid price available for sizing - skipping entry", holding.ticker)
        return 0

    price = float(last_price)

    if not math.isfinite(price) or price <= 0:
        log.warning("%s: no valid price available for sizing - skipping entry", holding.ticker)
        return 0

    target_dollars = holding.weight_pct / 100 * account_value
    quantity = math.floor(target_dollars / price)

    if quantity == 0:
        log.warning(
            "%s: target $%.2f buys zero whole shares at $%.2f - skipping",
            holding.ticker,
            target_dollars,
            price,
        )

    return quantity


def submit_entry(strategy: Strategy, holding: Holding, account_value: float) -> bool:
    """Size and submit one whole-share DAY market buy."""
    quantity = entry_quantity(strategy, holding, account_value)

    if quantity == 0:
        return False

    order = strategy.create_order(
        holding.ticker,
        quantity,
        "buy",
        order_type="market",
        time_in_force="day",
    )

    if not strategy.is_backtesting:
        trade_id = record_order(
            TradeOrder(
                strategy=STRATEGY,
                idea_id=holding.idea_id,
                symbol=holding.ticker,
                side="buy",
                target_quantity=quantity,
                submitted_at=strategy.get_datetime(),
            )
        )
        strategy.trade_ids_by_symbol[holding.ticker] = trade_id
        update_idea_status(STRATEGY, holding.idea_id, "executed")

    strategy.submit_order(order)

    target_dollars = holding.weight_pct / 100 * account_value
    log.info(
        "%s: market buy %d shares (target %.2f%% = $%.2f)",
        holding.ticker,
        quantity,
        holding.weight_pct,
        target_dollars,
    )

    return True


def enter_positions(strategy: Strategy, portfolio: Portfolio) -> None:
    """Submit one whole-share DAY market buy per long draft holding."""
    if not portfolio.holdings:
        log.warning("Draft portfolio is empty - nothing to submit")
        return

    account_value = float(strategy.portfolio_value)
    submitted = 0

    # This is where the orders are submitted to the broker from
    # They are pulled from the Portfolio() object populated by the agent
    for holding in portfolio.holdings.values():
        if holding.side != "long":
            log.warning(
                "%s: skipping %s idea - this sleeve is long-only",
                holding.ticker,
                holding.side,
            )
            continue

        if submit_entry(strategy, holding, account_value):
            submitted += 1

    log.info(
        "Entry submission complete: %d/%d holdings submitted",
        submitted,
        len(portfolio.holdings),
    )
