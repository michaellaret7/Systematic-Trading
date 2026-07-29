"""A minimal live strategy that buys Bitcoin, then logs account and BTC data.

On startup it submits a market order for 0.001 BTC. Every iteration then fetches the BTC
position, portfolio details, and latest BTC price and logs them on the ``systematic_trading``
tree, so the lines flow through the unified handler to stdout, to CloudWatch (real-time),
and into the S3 archive.

Run it live (paper by default) with::

    uv run live btc_ticker           # in this process
    uv run live btc_ticker cloud     # on a RunPod pod, streaming to CloudWatch + S3
"""

from lumibot.entities import Asset
from lumibot.strategies import Strategy

from systematic_trading.logging_setup import get_logger

log = get_logger(__name__)


class BtcTicker(Strategy):
    """Buys Bitcoin, then logs account and BTC data every iteration."""

    WARM_UP_TRADING_DAYS = 0

    parameters = {
        "symbol": "BTC",
        "quantity": 0.001,
        # Crypto trades 24/7, so a short heartbeat keeps the log lively.
        "sleeptime": "30S",
    }

    def initialize(self) -> None:
        # Crypto trades around the clock; without this the strategy defaults to
        # equity hours and sleeps until the stock market opens instead of ticking.
        self.set_market("24/7")

        self.sleeptime = self.parameters["sleeptime"]

        # Crypto is quoted against a fiat asset; Alpaca serves BTC/USD.
        self.base = Asset(self.parameters["symbol"], asset_type=Asset.AssetType.CRYPTO)
        self.quote = Asset("USD", asset_type=Asset.AssetType.FOREX)

        self.ticks = 0

        order = self.create_order(
            self.base,
            self.parameters["quantity"],
            "buy",
            quote=self.quote,
            order_type="market",
            time_in_force="gtc",
        )
        self.submit_order(order)

        log.info(
            "BTC ticker online — submitted %g BTC market order; streaming %s/USD every %s",
            self.parameters["quantity"],
            self.parameters["symbol"],
            self.sleeptime,
        )

    def on_trading_iteration(self) -> None:
        self.ticks += 1

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
