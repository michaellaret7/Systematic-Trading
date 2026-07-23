"""A minimal live strategy that streams BTC/USD prices via Alpaca and logs each one.

Not a trading strategy — it never submits an order. Its only job is to exercise the
logging pipeline end to end: every iteration fetches the latest BTC price and logs it on
the ``systematic_trading`` tree, so the line flows through the unified handler to stdout,
to CloudWatch (real-time), and into the S3 archive. Use it to confirm a live deployment's
logging works without touching the market.

Run it live (paper by default) with::

    uv run live btc_ticker           # in this process
    uv run live btc_ticker cloud     # on a RunPod pod, streaming to CloudWatch + S3
"""

from lumibot.entities import Asset
from lumibot.strategies import Strategy

from systematic_trading.logging_setup import get_logger

log = get_logger(__name__)


class BtcTicker(Strategy):
    """Logs the BTC/USD price every iteration — a read-only logging smoke test."""

    WARM_UP_TRADING_DAYS = 0

    parameters = {
        "symbol": "BTC",
        # Crypto trades 24/7, so a short heartbeat keeps the log lively.
        "sleeptime": "30S",
    }

    def initialize(self) -> None:
        self.sleeptime = self.parameters["sleeptime"]

        # Crypto is quoted against a fiat asset; Alpaca serves BTC/USD.
        self.base = Asset(self.parameters["symbol"], asset_type=Asset.AssetType.CRYPTO)
        self.quote = Asset("USD", asset_type=Asset.AssetType.FOREX)

        self.ticks = 0

        log.info(
            "BTC ticker online — streaming %s/USD every %s (no orders placed)",
            self.parameters["symbol"],
            self.sleeptime,
        )

    def on_trading_iteration(self) -> None:
        self.ticks += 1

        price = self.get_last_price(self.base, quote=self.quote)

        if price is None:
            log.warning(
                "tick %d: no %s/USD price available — skipping", self.ticks, self.base.symbol
            )
            return

        log.info("tick %d: %s/USD = $%.2f", self.ticks, self.base.symbol, float(price))
