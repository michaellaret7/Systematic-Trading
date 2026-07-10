# Systematic Trading

Systematic trading system with agents embedded in the investment process.

**Lumibot is the infrastructure layer only** — backtesting plus paper/live execution
through its native Alpaca broker. The strategies, agents, portfolio construction, and
data enrichment are all our own code and live under `src/systematic_trading/`.

## Stack

- **Execution / backtest engine:** [Lumibot](https://lumibot.lumiwealth.com) (native Alpaca broker)
- **Price feed:** Alpaca (live + backtest), via Lumibot
- **Data enrichment:** Financial Modeling Prep (fundamentals / macro), called directly in strategy logic
- **Env / packaging:** [uv](https://docs.astral.sh/uv/) + `pyproject.toml`, Python 3.13

## Setup

```bash
# 1. Install dependencies into a managed .venv
uv sync

# 2. Configure secrets
cp .env.example .env    # then fill in Alpaca + FMP keys
```

## Run

```bash
# Backtest the reference strategy (Yahoo daily data, no keys needed)
uv run python scripts/backtest.py

# Paper/live trade against Alpaca (paper by default; ALPACA_PAPER controls it)
uv run python scripts/run_trader.py

# Tests
uv run pytest
```

## Layout

```
src/systematic_trading/
  config.py        # env/secrets; alpaca_config() → Lumibot broker dict
  strategies/      # Lumibot Strategy subclasses (same class backtest + live)
  screeners/       # reusable stock screens consumed by strategies
  agents/          # LLM / tool-calling decision layer (broker-agnostic)
  portfolios/      # sizing, risk budgeting, signal → target weights
  data/            # supplementary data adapters (FMP lives here)
scripts/           # backtest.py, run_trader.py entry points
tests/             # smoke tests
```

## Data model (how it fits together)

- **Live/paper:** Alpaca is both broker and price feed — Lumibot streams it
  automatically. `self.get_last_price()` / `self.get_historical_prices()` just work.
- **Backtest:** pick a Lumibot data source (Yahoo=daily/free, Alpaca=intraday,
  `PandasDataBacktesting`=your own files).
- **FMP** is *not* a Lumibot data source. It's enrichment (fundamentals, macro) you
  call yourself via `systematic_trading.data.providers.fmp.FMPClient` alongside Alpaca prices.
