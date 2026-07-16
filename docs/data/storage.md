# Data Storage

The repository package is the only application code that knows physical storage
locations.

## S3

- `fundamentals/`: raw FMP statement Parquet files and the active-universe CSV.
- `screeners/fundamentals_panel.parquet`: the shared computed metrics panel.
- `prices/daily_ohclv.parquet`: split-adjusted daily OHLCV history.

Callers use repository functions rather than constructing S3 URIs or calling pandas
I/O against raw paths.

## DynamoDB

- `trade-ideas`: pending, executed, and rejected strategy proposals.
- `trade-ledger`: append-only paper/live fills.

The shared DynamoDB helper owns table construction, pagination, and numeric
deserialization. Domain records remain independent from boto3.
