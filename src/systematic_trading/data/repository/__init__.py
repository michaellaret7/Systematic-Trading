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
- **Trade ledger** (``ledger``) — append-only DynamoDB record of live/paper
  fills, one item per fill, keyed by strategy.
- **Trade ideas** (``ideas``) — DynamoDB queue of the fundamental agent's
  trade proposals: pending until the executor marks them executed/rejected.
"""

from systematic_trading.data.repository.fundamentals import (
    PERIODS,
    STATEMENTS,
    load_panel,
    load_sector_tags,
    load_statement,
    load_universe,
    panel_symbols,
    panel_uri,
    statement_columns,
    statement_uri,
    universe_uri,
    write_panel,
    write_statement,
    write_universe,
)
from systematic_trading.data.repository.ideas import (
    count_ideas_since,
    load_ideas,
    submit_idea,
    update_idea_status,
)
from systematic_trading.data.repository.ledger import (
    load_trades,
    record_fill,
)
from systematic_trading.data.repository.prices import (
    daily_prices_uri,
    load_daily_prices,
    write_daily_prices,
)

__all__ = [
    "PERIODS",
    "STATEMENTS",
    "count_ideas_since",
    "daily_prices_uri",
    "load_daily_prices",
    "load_ideas",
    "load_panel",
    "load_sector_tags",
    "load_statement",
    "load_trades",
    "load_universe",
    "panel_symbols",
    "panel_uri",
    "record_fill",
    "statement_columns",
    "statement_uri",
    "submit_idea",
    "universe_uri",
    "update_idea_status",
    "write_daily_prices",
    "write_panel",
    "write_statement",
    "write_universe",
]
