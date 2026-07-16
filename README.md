# Systematic Trading

Systematic trading system with strategy-owned workflows and agents embedded in
the investment process.

Lumibot is the execution infrastructure: backtesting plus paper/live trading
through its native Alpaca broker. Screening, agent research, workflow
orchestration, portfolio logic, and supplementary data are application code
under `src/systematic_trading/`.

## Setup

```bash
uv sync
cp .env.example .env
```

Fill in the services used by the job or strategy you intend to run. Paper mode
is the default; real-money trading requires an explicit `ALPACA_PAPER=false`.

## Commands

Run the offline test suite and quality checks:

```bash
uv run pytest
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
```

The generic runners accept one or more registered Lumibot strategies:

```bash
uv run backtest <strategy> --start 2024-01-01 --end 2024-12-31
uv run live <strategy>
```

The strategy registry is intentionally empty until the first complete strategy
adapter is implemented. Never run `live` unless opening a broker connection is
the explicit intent.

Scheduled data-maintenance jobs remain directly runnable:

```bash
uv run python scripts/push_fundamentals.py
uv run python scripts/push_daily_prices.py
uv run python scripts/update_daily_prices.py
uv run python -m systematic_trading.screener.fundamentals.build
```

## Architecture

```text
src/systematic_trading/
  domain/            # typed trade ideas and fills
  data/              # contracts, FMP adapter, S3/DynamoDB repositories
  agents/tools/      # broker-agnostic tools shared by strategy agents
  screener/          # reusable panel construction, metrics, and scoring
  strategies/        # strategy-owned screening, workflows, agents, Lumibot adapter
  backtest.py        # generic registered-strategy backtest runner
  live.py            # generic registered-strategy live/paper runner
```

CSF Champions is organized as one strategy bubble:

```text
strategies/csf_champions/
  strategy.py
  screening.py
  workflows/
  agents/
```

The workflow layer is broker-agnostic. `strategy.py` will decide when workflows
run and translate their results into Lumibot orders after its lifecycle and
execution contract are specified.

See `docs/architecture.md` for dependency rules and
`docs/strategies/csf_champions.md` for the current workflow status.
