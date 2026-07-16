# CSF Champions

CSF Champions is organized as a strategy-owned feature package.

```text
strategies/csf_champions/
  strategy.py
  screening.py
  workflows/generate_trade_ideas.py
  agents/ticker_analyst/
```

## Current workflow

`generate_trade_ideas()`:

1. Loads the strategy-specific Champions screen.
2. Selects the top 200 candidates.
3. Runs up to three ticker analysts concurrently.
4. Lets each analyst persist an actionable BUY through the shared trade-idea tool.
5. Isolates individual failures and logs a final batch result.

The workflow is callable application code, not a script. It contains no Lumibot
lifecycle methods and submits no broker orders.

## Strategy status

The Lumibot adapter is intentionally not implemented yet. Cadence, portfolio
construction, backtest behavior, order sequencing, and additional workflows must be
specified before the strategy is registered. Until then, the global strategy
registry remains empty and the generic runners expose no incomplete strategy.

Future workflows belong beside `generate_trade_ideas.py` when their real use cases
are defined. Do not create speculative workflow modules in advance.
