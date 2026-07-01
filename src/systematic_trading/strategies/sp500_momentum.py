"""Monthly long/short momentum over 30 large S&P 500 names, minute-level risk cap.

At the first iteration of each new month (and on startup), every name in the
universe is scored by its trailing 6-month (126 trading day) return. Positive
momentum is held long at a +3% target weight; negative momentum is held short at
-3%. Net exposure therefore floats with market breadth: a market where 25 of 30
names are rising runs ~75% long / 15% short.

Between rebalances the strategy wakes every minute with one job: if any position's
absolute weight has drifted above the 3% cap (plus a small buffer to avoid
one-share churn), it is trimmed back to target — longs by selling, shorts by
buying to cover. Uses the broker's (Alpaca) data feed.
"""

from __future__ import annotations

from lumibot.strategies import Strategy

from systematic_trading.logging_setup import get_logger

log = get_logger("sp500_momentum")

# 30 large-cap S&P 500 names spread across sectors (static for now — no FMP).
UNIVERSE: list[str] = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "V", "UNH",
    "XOM", "JNJ", "PG", "HD", "KO", "PEP", "MRK", "COST", "WMT", "CVX",
    "LLY", "ABBV", "BAC", "DIS", "CSCO", "MCD", "CAT", "HON", "NKE", "GE",
]

# (symbol, quantity, side, price) — one rebalance instruction.
RebalanceOrder = tuple[str, int, str, float]


class SP500Momentum(Strategy):
    """Long/short monthly momentum: 6-month winners +3%, losers -3%, drift-capped."""

    # Trading days of history a backtest preloads before the first iteration, so
    # the 126-day momentum score is available at the very first rebalance.
    WARM_UP_TRADING_DAYS = 140

    parameters = {
        "symbols": UNIVERSE,
        "momentum_days": 126,   # ~6 months of trading days
        "target_weight": 0.03,  # 3% per position (long or short); also the drift cap
        "trim_buffer": 0.001,   # only trim above 3.1% absolute, so a 1-tick move can't churn
    }

    def initialize(self) -> None:
        # Live runs at minute cadence; backtests step daily (minute-stepping a year
        # of simulated time is impractical, so drift trims are checked once per day).
        self.sleeptime = "1D" if self.is_backtesting else "1M"
        self.set_market("NYSE")

        self.last_rebalance_month: tuple[int, int] | None = None
        self.minutes_before_closing = 15

        log.info(
            "ready    | %d names | %dd momentum | +/-%.0f%% cap | long/short",
            len(self.parameters["symbols"]),
            self.parameters["momentum_days"],
            self.parameters["target_weight"] * 100,
        )

    def on_trading_iteration(self) -> None:
        now = self.get_datetime()
        month = (now.year, now.month)

        if month != self.last_rebalance_month:
            self._rebalance()
            self.last_rebalance_month = month
        else:
            self._trim_drifted()
    
    def before_market_closes(self) -> None:
        self.submit_order(self.create_order("SPY", 1, "buy"))

    def on_filled_order(self, position, order, price, quantity, multiplier) -> None:
        log.info(
            "fill     | %-4s %s %s @ %.2f", order.side.upper(), quantity, order.asset.symbol, price
        )

    def on_abrupt_closing(self) -> None:
        # Deliberately no sell_all(): the monthly book should survive restarts.
        log.info("abrupt shutdown — keeping positions (monthly book persists)")

    def _rebalance(self) -> None:
        """Move the book to target: winners long +3%, losers short -3%."""
        symbols: list[str] = self.parameters["symbols"]

        scores = {symbol: self._momentum(symbol) for symbol in symbols}
        longs = {symbol for symbol, m in scores.items() if m is not None and m > 0}
        shorts = {symbol for symbol, m in scores.items() if m is not None and m < 0}

        log.info("rebal    | %d long / %d short of %d names", len(longs), len(shorts), len(symbols))

        orders = self._rebalance_orders(longs, shorts)
        sells = [o for o in orders if o[2] in ("sell", "sell_short")]
        # Risk-reducing buys (short covers) go before buys that open new longs.
        buys = sorted((o for o in orders if o[2] in ("buy", "buy_to_cover")),
                      key=lambda o: o[2] != "buy_to_cover")

        # Sells first: long exits and new shorts raise the cash the buys draw on.
        for symbol, quantity, side, price in sells:
            self.submit_order(self.create_order(symbol, quantity, side))
            log.info("%-9s| %s %s @ ~%.2f (mom %+.1f%%)", side.upper(), quantity, symbol, price,
                     (scores[symbol] or 0) * 100)

        available = self.cash + sum(quantity * price for _, quantity, _, price in sells)

        for symbol, quantity, side, price in buys:
            quantity = min(quantity, int(available // price))

            if quantity < 1:
                log.info("skip     | %s: insufficient cash for target weight", symbol)
                continue

            self.submit_order(self.create_order(symbol, quantity, side))
            available -= quantity * price
            log.info("%-9s| %s %s @ ~%.2f (mom %+.1f%%)", side.upper(), quantity, symbol, price,
                     (scores[symbol] or 0) * 100)

    def _rebalance_orders(self, longs: set[str], shorts: set[str]) -> list[RebalanceOrder]:
        """Integer-share orders to reach target weights.

        Alpaca cannot flip a position through zero in one order, so a long<->short
        flip becomes two: close the existing position, then open the new one.

        Short entries/exits use the explicit ``sell_short`` / ``buy_to_cover`` sides:
        Lumibot's backtesting broker treats a plain "sell" as close-only and cancels
        it once the position is flat (guarding against unintended shorts). The live
        Alpaca broker maps the extended sides back to plain buy/sell for the API.
        """
        target_weight: float = self.parameters["target_weight"]
        portfolio_value = self.portfolio_value

        orders: list[RebalanceOrder] = []

        for symbol in self.parameters["symbols"]:
            price = self.get_last_price(symbol)

            if price is None:
                log.info("skip     | %s: no price available", symbol)
                continue

            position = self.get_position(symbol)
            held = int(position.quantity) if position is not None else 0

            size = int(portfolio_value * target_weight // price)
            target = size if symbol in longs else -size if symbol in shorts else 0

            if (held > 0 and target < 0) or (held < 0 and target > 0):
                orders.append((symbol, abs(held), "sell" if held > 0 else "buy_to_cover", price))
                orders.append((symbol, abs(target), "sell_short" if target < 0 else "buy", price))
                continue

            delta = target - held

            if delta > 0:
                orders.append((symbol, delta, "buy_to_cover" if held < 0 else "buy", price))
            elif delta < 0:
                orders.append((symbol, -delta, "sell" if held > 0 else "sell_short", price))

        return orders

    def _trim_drifted(self) -> None:
        """Bring any position whose absolute weight drifted above the cap back to target.

        Longs are trimmed by selling shares; shorts by buying some back.
        """
        cap: float = self.parameters["target_weight"]
        buffer: float = self.parameters["trim_buffer"]
        portfolio_value = self.portfolio_value

        for symbol in self.parameters["symbols"]:
            position = self.get_position(symbol)

            if position is None:
                continue

            quantity = int(position.quantity)

            if quantity == 0:
                continue

            price = self.get_last_price(symbol)

            if price is None:
                continue

            weight = quantity * price / portfolio_value  # negative for shorts

            if abs(weight) <= cap + buffer:
                continue

            excess = int((abs(weight) - cap) * portfolio_value / price)

            if excess < 1:
                continue

            side = "sell" if quantity > 0 else "buy_to_cover"

            self.submit_order(self.create_order(symbol, excess, side))
            log.info("TRIM     | %s %s %s: %.2f%% -> %+.2f%%", side.upper(), excess, symbol,
                     weight * 100, (cap if quantity > 0 else -cap) * 100)

    def _momentum(self, symbol: str) -> float | None:
        """Trailing ``momentum_days`` fractional return from daily closes."""
        days: int = self.parameters["momentum_days"]
        bars = self.get_historical_prices(symbol, days + 1, "day")

        if bars is None or len(bars.df) < days + 1:
            return None

        closes = bars.df["close"]

        return closes.iloc[-1] / closes.iloc[0] - 1
