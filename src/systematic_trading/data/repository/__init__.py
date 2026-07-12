"""The data repository: the only code that knows where our datasets live.

Everything above this layer — screeners, strategies, agents, tools — reads and
writes stored data through these functions, never by building S3 URIs or
calling ``read_parquet`` on raw paths. Providers (``data.providers``) are
called only by the push/build scripts that fill the repository.

Datasets:

- **Fundamentals** (``fundamentals``) — raw FMP statement parquets
  (5 statements x quarter/annual) plus the built metrics panel every
  fundamental screener reads from.
- **Prices** (``prices``) — the daily split-adjusted OHLCV parquet covering
  the trailing 4 years for every panel symbol.
"""

from systematic_trading.data.repository.fundamentals import (
    PERIODS,
    STATEMENTS,
    load_panel,
    load_statement,
    panel_symbols,
    panel_uri,
    statement_uri,
    write_panel,
    write_statement,
)
from systematic_trading.data.repository.prices import (
    daily_prices_uri,
    load_daily_prices,
    write_daily_prices,
)

__all__ = [
    "PERIODS",
    "STATEMENTS",
    "daily_prices_uri",
    "load_daily_prices",
    "load_panel",
    "load_statement",
    "panel_symbols",
    "panel_uri",
    "statement_uri",
    "write_daily_prices",
    "write_panel",
    "write_statement",
]
