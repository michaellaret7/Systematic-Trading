# Data Contracts

Data contracts make the implicit shape of DataFrames and DynamoDB records explicit
at the boundary where malformed data first enters the application.

## DataFrames

`systematic_trading.data.contracts` validates four stored dataset families:

- Raw statements require normalized `symbol` values and datetime `date` values.
- The fundamentals panel additionally requires `filingDate`, sector classification,
  and unique `(symbol, date)` rows.
- Daily prices require unique `(symbol, date)` rows and numeric OHLCV columns.
- The active universe requires unique, normalized symbols.

Write functions call these validators before sending data to S3. The contracts do
not impose speculative provider rules: raw statement amendments may still contain
multiple observations for the same fiscal period and are resolved by panel-building
policy.

## DynamoDB records

`systematic_trading.domain.ideas.TradeIdea` and
`systematic_trading.domain.trades.TradeOrder` are the typed application records.
Repositories accept these records and exclusively own:

- UUID and sort-key generation.
- Datetime serialization.
- DynamoDB `Decimal` conversion.
- Table names and expressions.
- Paper/live stamping for fills.

Strategies and agents never construct DynamoDB items directly.
