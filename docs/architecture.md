# Architecture

The project is a single modular Python application. Lumibot supplies backtesting
and broker execution; the application owns data enrichment, screening, workflows,
agents, portfolio decisions, and strategy policy.

## Dependency direction

```text
Lumibot strategy adapter
    -> strategy-owned workflows
        -> strategy screening and agents
        -> shared screener mechanics
        -> shared agent tools
        -> domain records
        -> data providers and repositories
```

Dependencies flow downward only:

- `domain` imports no pandas, AWS, FMP, agents, or Lumibot code.
- `data.providers` owns third-party vendor communication.
- `data.repository` owns storage locations and serialization.
- `screener` owns reusable DataFrame calculations and scoring mechanics.
- `agents.tools` owns tools reusable by more than one strategy.
- Each strategy package owns its policy, workflows, prompts, and specialized agents.
- `strategy.py` is the only strategy module that may depend on Lumibot lifecycle APIs.
- Workflows never import `strategy.py` or submit broker orders directly.

## Strategy bubbles

Each strategy is a cohesive feature package:

```text
strategies/<strategy>/
  strategy.py
  screening.py
  workflows/
  agents/
```

A strategy may own multiple workflows. Add one module per real use case; do not
create a workflow base class, registry, or engine. If behavior later becomes truly
shared by multiple strategies, extract the shared capability only after the second
caller exists.

## Operational jobs

Fixed scheduled jobs remain under `scripts/` and run directly. Reusable behavior
belongs under `src/systematic_trading/` only when multiple jobs call it or it forms
a meaningful test boundary. `data.price_sync` exists because both full and
incremental price jobs share that behavior.

## External boundaries

FMP, S3, DynamoDB, Alpaca, and model providers are true external dependencies.
Tests replace them at the boundary and never open network or broker connections.
The FMP REST client is intentionally separate from its Lumibot backtesting adapter
so ingestion code does not initialize the trading framework.
