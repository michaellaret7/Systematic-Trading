# LUMIBOT.md: Agent Reference for Writing Lumibot Strategies

Concise rules and API reference for generating Lumibot strategy code.
Source: lumibot.lumiwealth.com docs + Lumiwealth/lumibot repo (v4.x, 2026).

---

## 1. Core Model

- Everything is one class: `class MyStrategy(Strategy)`.
- **Lifecycle methods**: hooks the framework calls on you. You OVERRIDE these. All are plain `pass` stubs (not abstract); only `on_trading_iteration` is required in practice.
- **Strategy methods**: the API you CALL inside your overrides (`self.get_last_price`, `self.submit_order`, ...). Never override these.
- The main loop is **clock driven, not data event driven**: `on_trading_iteration` fires every `self.sleeptime` while the market is open. You pull data inside it; nothing is pushed.

## 2. Documentation Resources

**Lumibot docs: https://lumibot.lumiwealth.com/** — go here for anything framework-related. Check the docs before guessing at Lumibot API behavior; the framework has many non-obvious conventions.

Key pages (consult these directly — they cover most day-to-day work):

- **Strategy methods** — https://lumibot.lumiwealth.com/strategy_methods.html — everything callable on `self` inside a strategy: orders (`create_order`, `submit_order`), data (`get_last_price`, `get_historical_prices`), positions, account state.
- **Lifecycle methods** — https://lumibot.lumiwealth.com/lifecycle_methods.html — the hooks Lumibot calls (`initialize`, `on_trading_iteration`, `before_market_closes`, `on_filled_order`, `on_abrupt_closing`, …) and when each fires these are customizeable per stratgy.
- **Strategy properties** — https://lumibot.lumiwealth.com/strategy_properties.html — attributes like `self.cash`, `self.portfolio_value`, `self.sleeptime`, `self.is_backtesting`, `self.minutes_before_closing`.
- **Entities** — https://lumibot.lumiwealth.com/entities.html — the `Asset`, `Order`, `Position`, `Bars` objects that methods take and return.
- **Alpaca broker** — https://lumibot.lumiwealth.com/brokers.alpaca.html — our broker: config dict shape, supported order types/sides, quirks.
- **Examples** — https://lumibot.lumiwealth.com/examples.html — complete reference strategies showing idiomatic Lumibot patterns.

## 3. Lifecycle Methods (all 16, execution order)

| Method | When it fires | Typical use |
|---|---|---|
| `initialize(self, ...)` | Once at startup | Set `sleeptime`, `minutes_before_closing`, `set_market()`, params |
| `before_market_opens(self)` | Daily, pre open (skipped day 1 if market already open) | `cancel_open_orders()`, premarket prep |
| `before_starting_trading(self)` | Daily, always before trading starts | Reset per day state |
| `on_trading_iteration(self)` | Every `sleeptime` while market open | Main trading logic (REQUIRED) |
| `trace_stats(self, context, snapshot_before)` | After every iteration | Return dict -> columns in stats CSV. `context` = `locals()` of the iteration |
| `before_market_closes(self)` | `minutes_before_closing` before close | Flatten intraday positions |
| `after_market_closes(self)` | Daily, post close | EOD reporting, retraining |
| `on_strategy_end(self)` | Once at normal termination | Final cleanup/stats |
| `on_abrupt_closing(self)` | Ctrl+C / SIGTERM | Graceful exit, often `sell_all()` |
| `on_bot_crash(self, error)` | Unhandled exception | Alerting; default calls `on_abrupt_closing()` |
| `on_new_order(self, order)` | Async: broker accepted order | Logging |
| `on_partially_filled_order(self, order, price, quantity, multiplier)` | Async: partial fill | Track remaining = `order.quantity - quantity` |
| `on_filled_order(self, position, order, price, quantity, multiplier)` | Async: full fill | Attach stops, update state (preferred over polling) |
| `on_canceled_order(self, order)` | Async: cancel confirmed | Logging |
| `on_parameters_updated(self, parameters)` | After `self.update_parameters()` | Recompute derived state live |
| `tearsheet_custom_metrics(self, stats_df, strategy_returns, benchmark_returns, drawdown, drawdown_details, risk_free_rate)` | Backtest only, before tearsheet written | Return `{name: scalar}` extra metrics; `{}` if none |

## 4. Full Strategy API: Callable Methods (what you call, never override)

Complete list of documented `Strategy` methods, grouped as in the official docs.

**Orders**
`create_order`, `submit_order`, `submit_orders`, `cancel_order`, `cancel_orders`, `cancel_open_orders`, `sell_all`, `get_order`, `get_orders`, `get_selling_order` (builds the order that would close a position), `get_asset_potential_total` (position qty + pending order qty), `close_position`

**Data**
`get_last_price`, `get_last_prices`, `get_quote` (bid/ask/mid), `get_historical_prices`, `get_historical_prices_for_assets` (batch), `get_next_trading_day`, `get_yesterday_dividend`

**Account**
`get_position`, `get_positions`, `get_cash`, `get_portfolio_value` (also `self.cash` / `self.portfolio_value` properties), `get_parameters`, `set_parameters`, `deposit_cash`, `withdraw_cash`, `adjust_cash`, `configure_cash_financing`, `set_cash_financing_rates` (margin/financing modeling in backtests)

**Options**
`get_chains` (all expirations/strikes per exchange), `get_chain` (single exchange), `get_expiration`, `get_strikes`, `get_greeks`, `get_multiplier`, `options_expiry_to_datetime_date`, plus the `self.options_helper` object (`find_strike_for_delta`, `get_expiration_on_or_after_date`) which is the preferred selection path

**Date/Time** (all backtest aware; these return simulated time in backtests)
`get_datetime`, `get_timestamp`, `get_datetime_range`, `get_round_minute`, `get_round_day`, `get_last_minute`, `get_last_day`, `localize_datetime`, `to_default_timezone`

**Chart / indicators (tearsheet output)**
`add_line`, `add_marker`, `get_lines_df`, `get_markers_df`

**Misc / control flow**
`log_message`, `set_market`, `update_parameters`, `register_cron_callback`, `sleep` (framework aware pause; NOT `time.sleep`), `await_market_to_open`, `await_market_to_close`, `wait_for_order_registration`, `wait_for_order_execution`, `wait_for_orders_registration`, `wait_for_orders_execution`

Notes:
- `self.sleep(n)` is the framework's own pause and is safe where `time.sleep` is not; still prefer stateless per iteration logic via `self.vars`.
- `wait_for_order_execution(order)` blocks until fill and is the synchronous alternative to the `on_filled_order` callback; use sparingly in live trading.
- `await_market_to_open(timedelta_min)` is useful inside custom flows to park until N minutes before the open.

## 4b. Usage Snippets (most used calls)

**Orders**
```python
order = self.create_order(asset, qty, "buy")                     # market
order = self.create_order(asset, qty, "buy", limit_price=123.45) # limit
order = self.create_order(asset, qty, "sell", stop_price=118.0)  # stop
# Bracket (take profit + stop loss). Do NOT use deprecated
# take_profit_price / stop_loss_price kwargs:
order = self.create_order(asset, 100, "buy",
    order_class=Order.OrderClass.BRACKET,
    secondary_limit_price=110,   # take profit
    secondary_stop_price=90)     # stop loss
self.submit_order(order)         # also submit_orders([...])
self.cancel_order(order); self.cancel_open_orders()
self.sell_all()                  # liquidate everything
self.close_position(asset)       # REQUIRED to close crypto futures
```

**Data**
```python
price = self.get_last_price(asset)            # real time last trade. CAN RETURN None
quote = self.get_quote(asset)                 # bid/ask; use quote.mid_price
bars  = self.get_historical_prices(asset, 20, "day")   # also "minute"
df    = bars.df                               # pandas OHLCV, tz aware index
prices = self.get_last_prices([a1, a2])
chains = self.get_chains(underlying)          # options chains
greeks = self.get_greeks(option_asset)        # can be None
```

**Account / state**
```python
self.get_position(asset)      # None if flat
self.get_positions()
self.get_orders()
self.portfolio_value          # property
self.cash                     # property
self.first_iteration          # True only on first loop pass
```

**Time / config / util**
```python
self.get_datetime()           # simulated time in backtests. NEVER datetime.now()
self.set_market("NASDAQ")     # "24/7" REQUIRED for crypto; "us_futures" for futures
self.update_parameters({...})
self.log_message("msg", color="red")
self.register_cron_callback(schedule, func)   # custom scheduled hooks
```

**Charting (backtest tearsheet)**
```python
self.add_line("SMA_20", val, color="blue", asset=a)   # continuous series
self.add_marker("Buy", price, color="green", asset=a, detail_text="why")
# markers ONLY on events, never every iteration. No `text=` kwarg; use detail_text.
# Always pass asset= to overlay on the price chart.
```

## 5. Entities

```python
from lumibot.entities import Asset, Order

Asset("SPY")                                          # stock (str also accepted)
Asset("SPY", asset_type=Asset.AssetType.STOCK)
Asset("BTC", asset_type=Asset.AssetType.CRYPTO)
Asset("SPY", asset_type=Asset.AssetType.OPTION,
      expiration=date(2026, 8, 21), strike=550, right="call")   # multiplier = 100
Asset("ES", asset_type=Asset.AssetType.FUTURE, expiration=...)
```
- `Position`: `.quantity`, `.asset`, `.avg_fill_price`
- `Order`: `.symbol`, `.quantity`, `.side`, `.status`, `.limit_price`
- `Bars`: `.df` pandas DataFrame (open/high/low/close/volume)

## 6. Boilerplate

**Backtest**
```python
from datetime import datetime
from lumibot.backtesting import PolygonDataBacktesting  # or YahooDataBacktesting, ThetaDataBacktesting
from lumibot.strategies import Strategy

class MyStrategy(Strategy):
    parameters = {"symbol": "SPY"}   # define params HERE, one place only

    def initialize(self):
        self.sleeptime = "1D"

    def on_trading_iteration(self):
        ...

if __name__ == "__main__":
    result = MyStrategy.run_backtest(
        PolygonDataBacktesting,
        datetime(2025, 1, 1),
        datetime(2025, 6, 1),
        benchmark_asset="SPY",
        polygon_api_key="...",
    )
# Outputs: tearsheet HTML, stats CSV, trades CSV, indicators HTML
# Env var alternative: IS_BACKTESTING, BACKTESTING_START, BACKTESTING_END,
# BACKTESTING_DATA_SOURCE (then pass None as datasource)
```

**Live**
```python
from lumibot.traders import Trader
from lumibot.brokers import Alpaca   # or InteractiveBrokers, Tradier, Schwab, Ccxt...

ALPACA_CONFIG = {"API_KEY": "...", "API_SECRET": "...", "PAPER": True}

trader = Trader()
broker = Alpaca(ALPACA_CONFIG)
strategy = MyStrategy(broker=broker)
trader.add_strategy(strategy)
trader.run_all()
```
Credentials can also come from env vars / `.env` (e.g. `ALPACA_API_KEY`, `ALPACA_API_SECRET`, `ALPACA_IS_PAPER`, `POLYGON_API_KEY`, `THETADATA_USERNAME/PASSWORD`).

## 7. CRITICAL RULES (from official common_mistakes docs)

1. **NEVER `datetime.now()` / `datetime.today()`.** Always `self.get_datetime()`. Otherwise backtests use wall clock time and results are garbage.
2. **NEVER `from __future__ import annotations`.** Crashes backtesting. Remove it.
3. **Custom state goes on `self.vars`, not bare `self`.** `self.name`, `self.asset`, `self.symbol` etc. collide with framework internals. Use `self.vars.my_thing = ...`.
4. **Crypto requires `self.set_market("24/7")`** in `initialize`, or the bot stops at 4pm ET.
5. **`get_last_price()` can return `None`.** Always check before dividing/sizing. Same for `get_quote()` and `get_greeks()`; if greeks are None, skip that check and continue, do not `return` and kill the whole iteration.
6. **Real time price = `get_last_price` / `get_quote`,** not `get_historical_prices(..., 1, "minute")` (stale).
7. **Options are 100x.** Cost per contract = premium * 100. Size accordingly.
8. **Options pricing: use `get_quote` mid,** not `get_last_price` (stale for illiquid strikes).
9. **Option selection: use `self.options_helper`** (`get_expiration_on_or_after_date`, `find_strike_for_delta`). Never construct arbitrary expirations or brute force scan strikes with repeated `get_greeks` (extremely slow).
10. **Positions do NOT update immediately after `submit_order()`.** Check on the next iteration, or use `on_filled_order`.
11. **Crypto futures: close with `close_position()`,** not an opposite side `submit_order` (that opens a new position).
12. **Bracket orders: `order_class=Order.OrderClass.BRACKET` + `secondary_limit_price` / `secondary_stop_price`.** The `take_profit_price` / `stop_loss_price` kwargs are deprecated.
13. **Never `time.sleep()` in a strategy.** It blocks the whole bot. Persist a timestamp in `self.vars` and check elapsed time next iteration.
14. **No bare `try/except: pass`.** Handle `None` explicitly and `log_message(..., color="red")`.
15. **Parameters defined in exactly one place** (the class level `parameters` dict). Do not also pass overrides in the constructor.
16. **No hardcoded API keys** and no fake fallback key strings. `os.getenv(...)` with a `None` check.
17. **Never fabricate market data.** If bars are missing, skip/log; do not forward fill, interpolate, or invent placeholder bars.
18. **Chart hygiene:** `add_marker` only on events, `add_line` for continuous series, always pass `asset=`, use `detail_text=` (there is no `text=` param).

## 8. Custom Data Provider (Pandas Backtesting)

Use `PandasDataBacktesting` to backtest on your own data (CSV, parquet, database, any source). This is the custom data path; Polygon/Yahoo/ThetaData are easier if their data suffices.

**Strict dataframe contract** (anything else is rejected):
- Index: name `datetime`, dtype `datetime64` (timezone aware; default TZ America/New_York)
- Columns: exactly `["open", "high", "low", "close", "volume"]`, float
- Timesteps supported: `"minute"` or `"day"` only

**Pattern**
```python
import pandas as pd
from lumibot.backtesting import PandasDataBacktesting
from lumibot.entities import Asset, Data
from lumibot.strategies import Strategy

df = pd.read_csv("AAPL.csv")   # must conform to the contract above
asset = Asset(symbol="AAPL", asset_type=Asset.AssetType.STOCK)  # Asset REQUIRED, not a str

pandas_data = {
    asset: Data(asset, df, timestep="minute"),
    # add more {Asset: Data} pairs for multi asset backtests
}

result = MyStrategy.run_backtest(
    PandasDataBacktesting,
    pandas_data[asset].datetime_start,   # or explicit datetimes
    pandas_data[asset].datetime_end,
    pandas_data=pandas_data,
)
```

Rules:
- Key the `pandas_data` dict with `Asset` objects, never plain symbol strings.
- `Data(...)` also accepts `quote=` (defaults USD), `date_start/date_end`, and `trading_hours_start/end` for custom sessions.
- Works for stocks, futures, crypto, and forex. Options expiration in Pandas backtests follows broker style settlement (physical for equity options, cash for index options; statuses `assigned` / `exercised` / `cash_settled` / `expired` land in trade artifacts).
- Missing data must stay missing. Never forward fill or synthesize bars to keep a backtest alive.

## 9. Fees, Slippage, Smart Limit Orders

**Trading fees** (backtest realism):
```python
from lumibot.entities import TradingFee
fee = TradingFee(flat_fee=0.0, percent_fee=0.001, per_contract_fee=0.65)
MyStrategy.run_backtest(..., buy_trading_fees=[fee], sell_trading_fees=[fee])
```

**Slippage** (backtest only, used by SMART_LIMIT fills):
```python
from lumibot.entities import TradingSlippage
slip = TradingSlippage(amount=0.05)
MyStrategy.run_backtest(..., buy_trading_slippages=[slip], sell_trading_slippages=[slip])
```

**SMART_LIMIT orders**: midpoint chasing limit ladder (Option Alpha SmartPricing parity). Walks from mid toward bid/ask on a timer; presets FAST (3 levels x 5s), NORMAL (4 x 10s), PATIENT (5 x 20s), 120s final hold. Backtests fill at mid +/- slippage; downgrades to market if bid/ask missing.
```python
from lumibot.entities import SmartLimitConfig, SmartLimitPreset
cfg = SmartLimitConfig(preset=SmartLimitPreset.NORMAL, slippage=0.05)
order = self.create_order("SPY", 100, "buy", smart_limit=cfg)
```
Multi leg: parent order with `order_class=Order.OrderClass.MULTILEG` and legs on `child_orders`; fills atomically at net mid + slippage.

## 10. Futures Asset Types

```python
Asset("ES", asset_type=Asset.AssetType.CONT_FUTURE)          # continuous: PREFERRED for backtests, no roll management
Asset("ES", asset_type=Asset.AssetType.FUTURE, expiration=date(2026, 12, 18))  # specific contract (live)
Asset("MES", asset_type=Asset.AssetType.FUTURE, auto_expiry=Asset.AutoExpiry.FRONT_MONTH)  # live front month
```
Common symbols: ES/MES, NQ/MNQ, CL, GC. Use `set_market("us_futures")`. Remember `close_position()` for crypto futures.

## 11. State Persistence

- `self.vars` survives across iterations in one run. Locals inside `on_trading_iteration` do not.
- Set env var `DB_CONNECTION_STR` (any SQLAlchemy string) and Lumibot auto backs up `self.vars` after every iteration and restores it on startup, so state survives bot restarts.

## 12. Built-In Point-in-Time Data Tools

**SEC fundamentals** (no API key, cached, backtest safe: gated to filings known as of `self.get_datetime()`):
```python
self.fundamentals.get_income_statement("AAPL")
self.fundamentals.get_balance_sheet("AAPL")
self.fundamentals.get_cash_flow("AAPL")
self.fundamentals.get_company_facts("AAPL")          # compact by default; raw=True for full payload
self.fundamentals.get_filings("AAPL", form="10-K")
self.fundamentals.search_filing("AAPL", accession_number=..., query="risk")
```

**FRED macro** (requires `FRED_API_KEY`; backtests request point-in-time vintages as of the sim clock):
```python
self.macro.get_series("DGS10")
self.macro.get_latest("UNRATE")
self.macro.get_snapshot(["FEDFUNDS", "DGS10", "CPIAUCSL", "UNRATE"])
```

## 13. Key Environment Variables

- `IS_BACKTESTING`, `BACKTESTING_START`, `BACKTESTING_END`, `BACKTESTING_DATA_SOURCE` (pass `None` as datasource to auto select)
- Broker creds: `ALPACA_API_KEY` / `ALPACA_API_SECRET` / `ALPACA_IS_PAPER`, IBKR/Tradier/Schwab equivalents
- Data: `POLYGON_API_KEY`, `THETADATA_USERNAME` / `THETADATA_PASSWORD`, `FRED_API_KEY`
- Persistence: `DB_CONNECTION_STR`
- Caches: `LUMIBOT_FRED_CACHE_DIR`, `LUMIBOT_SEC_CACHE_DIR` (defaults under `~/.lumibot/cache/`)
- Notifications: Discord/Telegram webhook vars documented in `environment_variables.rst`

## 14. Quick Facts

- `sleeptime` formats: `"30S"`, `"5M"`, `"1H"`, `"1D"`.
- Default market calendar is NASDAQ; `set_market()` supports `"24/7"`, `"us_futures"`, and many exchange calendars.
- Backtest data sources: Yahoo (free, daily), Polygon, ThetaData (options), DataBento (futures), IBKR, Pandas (custom CSV/DataFrame).
- Stats: `trace_stats` rows land in the backtest CSV; `tearsheet_custom_metrics` appends rows to the QuantStats tearsheet (values are literal scalars, no % inference).
- Repo ships `llms.txt` / `llms-full.txt` at the root of Lumiwealth/lumibot for deeper agent navigation of the docs.