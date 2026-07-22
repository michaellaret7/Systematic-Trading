# Alpaca Account & Portfolio Data Through Lumibot

What Alpaca's brokerage API returns about the account and portfolio, and the
(much smaller) subset Lumibot surfaces to a strategy. Verified against the
installed Lumibot source (v4.5.63, `.venv/Lib/site-packages/lumibot/`), the
[Lumibot docs](https://lumibot.lumiwealth.com/), and the
[Alpaca API reference](https://docs.alpaca.markets/reference/getaccount-1).

## TL;DR

Inside a strategy, Lumibot exposes exactly three account numbers — cash,
positions value, portfolio value — plus `Position` and `Order` objects.
Everything else Alpaca sends (buying power, margin, day-trade count, PDT flag,
…) is discarded, but remains reachable through `self.broker.api`, the raw
alpaca-py `TradingClient`.

## Account data

On each balance sync (`lumibot/brokers/alpaca.py`, `_get_balances_at_broker`),
Lumibot calls Alpaca's `GET /v2/account` and reads only four fields:

| Alpaca field | Becomes in Lumibot |
|---|---|
| `cash` | `self.cash` / `self.get_cash()` |
| `long_market_value` − `short_market_value` | internal positions value |
| `portfolio_value` | `self.portfolio_value` / `self.get_portfolio_value()` |

Discarded (no Lumibot property exists for any of these): `buying_power`,
`regt_buying_power`, `daytrading_buying_power`, `equity`, `last_equity`,
`initial_margin`, `maintenance_margin`, `multiplier`, `sma`, `daytrade_count`,
`pattern_day_trader`, `shorting_enabled`, `trading_blocked`, `accrued_fees`,
and every other field on the
[account endpoint](https://docs.alpaca.markets/reference/getaccount-1).

Nuances:

- Live `self.portfolio_value` is Alpaca's number verbatim (Alpaca documents
  `portfolio_value` as identical to `equity`). In backtests it is Lumibot's own
  mark-to-market: cash + Σ positions × last price. `_update_portfolio_value`
  early-returns in live mode, so live never recomputes it locally.
- `self.cash` serves a value cached for up to 59 seconds;
  `self.get_cash()` forces a fresh API call (and returns `None` on failure).

## Position data

`_parse_broker_position` maps Alpaca positions onto Lumibot `Position` objects:

| Kept | Dropped |
|---|---|
| `symbol` → `asset` | `cost_basis` |
| `qty` → `quantity` | `unrealized_plpc` |
| `avg_entry_price` → `avg_fill_price` | `unrealized_intraday_pl` / `_plpc` |
| `unrealized_pl` → `pnl` | `lastday_price`, `change_today` |
| `current_price` | `qty_available` |
| `market_value` | `exchange`, `asset_marginable` |
| `side` (LONG/SHORT) | |

Caveats:

- `Position.pnl_percent` exists on the entity but the Alpaca parser never sets
  it — it is always `None` for Alpaca positions.
- `position._raw` is **not** populated (the parser never calls `update_raw`),
  so the raw Alpaca position object is not retained on the Lumibot `Position`.

Full Alpaca field list:
[positions endpoint](https://docs.alpaca.markets/reference/getallopenpositions).

## Order data

Orders map far more completely (`_parse_broker_order`): asset, quantity, side,
order type/class, limit/stop/trail prices, time-in-force, `avg_fill_price`,
broker order id (`identifier`), created/updated timestamps, and status.

Alpaca statuses are normalized through Lumibot's `STATUS_ALIAS_MAP`:

| Alpaca | Lumibot |
|---|---|
| `filled` | `fill` |
| `partially_filled` | `partial_fill` |
| `accepted`, `held`, `pending_review`, `calculated` | `open` |
| `pending_new` | `new` |
| `done_for_day`, `replaced`, `stopped`, `suspended`, `pending_cancel`, `pending_replace` | `canceled` |
| `rejected` | `error` |
| `expired` | `expired` |

Unlike positions, orders keep the full raw Alpaca response at `order._raw` —
unmapped fields like `filled_qty`, `client_order_id`, `filled_at`, and
`extended_hours` are reachable there.

## Strategy accessors: broker-truth vs computed

| Accessor | Live source | Backtest source |
|---|---|---|
| `self.cash` | Alpaca `cash` (≤59 s cache) | Lumibot ledger |
| `self.get_cash()` | Alpaca `cash` (forced refresh) | Lumibot ledger |
| `self.portfolio_value` | Alpaca `portfolio_value` (last synced) | Lumibot mark-to-market |
| `self.get_portfolio_value()` | Alpaca `portfolio_value` (forced refresh) | Lumibot mark-to-market |
| `self.get_position(s)()` | Refreshed from broker, then local tracked | Local tracked |
| `self.get_orders()` | Refreshed from broker, then local tracked | Local tracked |

Because live `portfolio_value` is Alpaca's figure and backtest is Lumibot's,
the two can legitimately disagree with cash + Σ `get_positions()` market values
in live trading — the live path trusts Alpaca's marks.

## Escape hatch: `self.broker.api`

`self.broker.api` is the underlying `alpaca.trading.client.TradingClient`
(alpaca-py). It is the only route to anything Lumibot drops:

```python
account = self.broker.api.get_account()          # buying_power, maintenance_margin,
                                                 # daytrade_count, pattern_day_trader, ...
positions = self.broker.api.get_all_positions()  # cost_basis, unrealized_plpc, ...
```

Also useful: `self.broker.get_historical_account_value()` wraps Alpaca's
[portfolio-history endpoint](https://docs.alpaca.markets/reference/getaccountportfoliohistory-1)
and returns the account equity curve as minute/hour/day DataFrames; there is no
strategy-level method for it.
