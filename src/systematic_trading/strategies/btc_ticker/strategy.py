"""A minimal live strategy that trades a tiny amount of Bitcoin every iteration.

Each trading iteration submits a market buy sized to Alpaca's crypto minimum
notional ($10). Every 5th iteration also submits a matching market sell when
the position can cover it. No DynamoDB bookkeeping — Alpaca is the sole
position and order source.

Run it live (paper by default) with::

    uv run live btc_ticker           # in this process
    uv run live btc_ticker cloud     # on a RunPod pod, streaming to CloudWatch + S3
"""

from math import isfinite

from lumibot.entities import Asset
from lumibot.strategies import Strategy

from systematic_trading.logging_setup import get_logger

log = get_logger(__name__)

SELL_EVERY_N_TICKS = 5

# Alpaca crypto: notional must be >= $10 (error 40310000).
ALPACA_MIN_NOTIONAL_USD = 10.0
NOTIONAL_BUFFER = 1.05


# ====================================
# --> Helper funcs
# ====================================


def iteration_quantity(strategy: Strategy) -> float | None:
    """Return a BTC size that clears Alpaca's minimum notional, or None."""
    configured = float(strategy.parameters["quantity"])
    raw_price = strategy.get_last_price(strategy.base, quote=strategy.quote)

    if raw_price is None:
        log.warning("tick %d: no price for sizing - skipping order", strategy.ticks)
        return None

    price = float(raw_price)

    if not isfinite(price) or price <= 0:
        log.warning("tick %d: invalid price %s - skipping order", strategy.ticks, raw_price)
        return None

    min_qty = (ALPACA_MIN_NOTIONAL_USD * NOTIONAL_BUFFER) / price
    quantity = max(configured, min_qty)

    if quantity > configured:
        log.info(
            "tick %d: raised size %g → %g BTC to clear $%.0f min notional @ $%.2f",
            strategy.ticks,
            configured,
            quantity,
            ALPACA_MIN_NOTIONAL_USD,
            price,
        )

    return quantity


def submit_iteration_order(strategy: Strategy, side: str, quantity: float) -> None:
    """Submit one fractional market order for this heartbeat."""
    order = strategy.create_order(
        strategy.base,
        quantity,
        side,
        quote=strategy.quote,
        order_type="market",
        time_in_force="gtc",
    )
    strategy.submit_order(order)
    log.info(
        "tick %d: submitted market %s %g %s",
        strategy.ticks,
        side,
        quantity,
        strategy.base.symbol,
    )


def maybe_submit_iteration_sell(strategy: Strategy, quantity: float) -> None:
    """On every Nth tick, sell one clip if the broker position can cover it."""
    if strategy.ticks % SELL_EVERY_N_TICKS != 0:
        return

    position = strategy.get_position(strategy.base)
    held = abs(float(position.quantity)) if position is not None else 0.0

    if held + 1e-12 < quantity:
        log.warning(
            "tick %d: skip sell %g %s — held %g",
            strategy.ticks,
            quantity,
            strategy.base.symbol,
            held,
        )
        return

    submit_iteration_order(strategy, "sell", quantity)


class BtcTicker(Strategy):
    """Buys a min-notional BTC clip every iteration; sells one every 5th tick."""

    WARM_UP_TRADING_DAYS = 0

    parameters = {
        "symbol": "BTC",
        "quantity": 0.00001,
        "sleeptime": "30S",
    }

    def initialize(self) -> None:
        # Crypto trades around the clock; without this the strategy defaults to
        # equity hours and sleeps until the stock market opens instead of ticking.
        self.set_market("24/7")

        self.sleeptime = self.parameters["sleeptime"]
        self.base = Asset(self.parameters["symbol"], asset_type=Asset.AssetType.CRYPTO)
        self.quote = Asset("USD", asset_type=Asset.AssetType.FOREX)
        self.ticks = 0

        log.info(
            "BTC ticker online — target %g BTC every %s (min notional $%.0f); "
            "sell every %d ticks (%s/USD)",
            float(self.parameters["quantity"]),
            self.sleeptime,
            ALPACA_MIN_NOTIONAL_USD,
            SELL_EVERY_N_TICKS,
            self.base.symbol,
        )

    def on_trading_iteration(self) -> None:
        self.ticks += 1

        if not self.is_backtesting:
            quantity = iteration_quantity(self)

            if quantity is not None:
                submit_iteration_order(self, "buy", quantity)
                maybe_submit_iteration_sell(self, quantity)

        btc_position = self.get_position(self.base)

        if btc_position:
            position_info = btc_position.to_minimal_dict()
            cost_basis = abs(btc_position.quantity * btc_position.avg_fill_price)
            position_info["pnl_pct"] = round(float(btc_position.pnl) / cost_basis * 100, 2)
        else:
            position_info = "none"

        log.info(
            "BTC position: %s | portfolio value: $%.2f | cash: $%.2f",
            position_info,
            float(self.get_portfolio_value()),
            float(self.get_cash()),
        )

        price = self.get_last_price(self.base, quote=self.quote)

        if price is None:
            log.warning(
                "tick %d: no %s/USD price available — skipping", self.ticks, self.base.symbol
            )
            return

        log.info("tick %d: %s/USD = $%.2f", self.ticks, self.base.symbol, float(price))
