# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Single package (`systematic-trading`) managed by **uv**. Python `>=3.12,<3.14`; `.python-version` pins 3.13. `uv sync` installs everything (dev tooling included via the default `dev` dependency group; skip with `--no-dev`).

Entry points (defined in `[project.scripts]`):
- `uv run backtest <strategy> [...]` — backtest one or more registered strategies on Alpaca historical data. Flags: `--start`, `--end` (ISO dates), `--budget`. Outputs (stats CSV, trades, HTML tearsheet) land in `logs/`.
- `uv run live <strategy> [...]` — paper/live trade on Alpaca. All named strategies share one broker connection in a single `Trader` until Ctrl+C. **Paper by default** — real money only when `ALPACA_PAPER=false`.

Strategy names come from the `STRATEGIES` registry in `src/systematic_trading/strategies/__init__.py` (e.g. `uv run backtest sp500_momentum`).

Other commands:
- `uv run pytest` — smoke tests (`tests/test_smoke.py`); no network, no orders.
- `uv run ruff check` / `uv run ruff format` — lint/format (line length 100).

`scripts/` holds older single-strategy entry points (`backtest_sp500_momentum.py`, `run_sp500_momentum.py`); the generic runners above are the preferred interface.

## Documentation

**Lumibot docs: https://lumibot.lumiwealth.com/** — go here for anything framework-related. Check the docs before guessing at Lumibot API behavior; the framework has many non-obvious conventions.

Key pages (consult these directly — they cover most day-to-day work):

- **Strategy methods** — https://lumibot.lumiwealth.com/strategy_methods.html — everything callable on `self` inside a strategy: orders (`create_order`, `submit_order`), data (`get_last_price`, `get_historical_prices`), positions, account state.
- **Lifecycle methods** — https://lumibot.lumiwealth.com/lifecycle_methods.html — the hooks Lumibot calls (`initialize`, `on_trading_iteration`, `before_market_closes`, `on_filled_order`, `on_abrupt_closing`, …) and when each fires.
- **Strategy properties** — https://lumibot.lumiwealth.com/strategy_properties.html — attributes like `self.cash`, `self.portfolio_value`, `self.sleeptime`, `self.is_backtesting`, `self.minutes_before_closing`.
- **Entities** — https://lumibot.lumiwealth.com/entities.html — the `Asset`, `Order`, `Position`, `Bars` objects that methods take and return.
- **Alpaca broker** — https://lumibot.lumiwealth.com/brokers.alpaca.html — our broker: config dict shape, supported order types/sides, quirks.
- **Examples** — https://lumibot.lumiwealth.com/examples.html — complete reference strategies showing idiomatic Lumibot patterns.

## Architecture

**Lumibot is the infrastructure layer only** — backtesting plus paper/live execution through its native Alpaca broker. Strategies, agents, portfolio construction, and data enrichment are our own code under `src/systematic_trading/`. Keep that boundary: we don't fork or monkey-patch Lumibot; we subclass `Strategy` and wire brokers/data sources in the runners.

### Layout

```
src/systematic_trading/
  config.py          # env/secrets; alpaca_config() → Lumibot broker dict
  logging_setup.py   # two-channel logging (quiet Lumibot / concise strategy narrative)
  backtest.py        # `uv run backtest` — generic runner over STRATEGIES
  live.py            # `uv run live` — generic runner over STRATEGIES
  strategies/        # Lumibot Strategy subclasses + STRATEGIES registry
  agents/            # LLM / tool-calling decision layer (broker-agnostic)
  data/              # supplementary data adapters (FMP lives here)
scripts/             # legacy single-strategy entry points
tests/               # smoke tests
logs/                # backtest outputs (tearsheets, stats, trades) — git-ignored
```

### The strategy contract

Each strategy subclasses `lumibot.strategies.Strategy`. **The same class runs in backtest, paper, and live** — only the broker/data-source wiring in the runner changes. Guard against anything that would break this symmetry (e.g. use `self.get_datetime()`, never `datetime.now()`; use `self.is_backtesting` to branch where cadence must differ).

To add a strategy:
1. Subclass `Strategy` in a new module under `strategies/`.
2. Define `WARM_UP_TRADING_DAYS` on the class — the backtest runner preloads that much daily history so indicators are warm at the first iteration (e.g. `SP500Momentum` needs 140 for its 126-day momentum score).
3. Register it in the `STRATEGIES` dict in `strategies/__init__.py` under the CLI name you want.

Tunables go in the class-level `parameters` dict (Lumibot convention), not module constants.

### Non-obvious Lumibot/Alpaca invariants (learned the hard way)

- **Shorts need explicit sides.** Lumibot's backtesting broker treats a plain `"sell"` as close-only and cancels it once the position is flat. Short entries/exits must use `"sell_short"` / `"buy_to_cover"`; the live Alpaca broker maps them back to plain buy/sell for the API. See `SP500Momentum._rebalance_orders`.
- **Alpaca can't flip a position through zero in one order.** A long↔short flip is two orders: close the existing position, then open the new one.
- **Order sequencing matters for cash.** Submit sells (long exits, new shorts) before buys, and risk-reducing buys (`buy_to_cover`) before new-long buys; size buys against the cash the sells raise.
- **Backtests step daily, live runs at minute cadence.** Minute-stepping a year of simulated time is impractical, so `sleeptime` is `"1D"` when `self.is_backtesting`, `"1M"` live. Intraday logic (like drift trims) therefore runs once per simulated day in backtests.
- **`on_abrupt_closing` deliberately does NOT `sell_all()`** — the monthly book should survive restarts. Don't "fix" this.
- **Windows console encoding.** `configure_logging()` forces UTF-8 on stdout/stderr because cp1252 chokes on Lumibot's Unicode progress bar and aborts backtests mid-run. Don't remove it.

### Data model

- **Live/paper:** Alpaca is both broker and price feed — Lumibot streams it automatically. `self.get_last_price()` / `self.get_historical_prices()` just work.
- **Backtest:** `AlpacaBacktesting` (same keys as live). Other Lumibot data sources (Yahoo, `PandasDataBacktesting`, ThetaData via the `thetadata` extra) are options when needed.
- **FMP is NOT a Lumibot data source.** Financial Modeling Prep is enrichment (fundamentals, macro) called directly from strategy/agent logic via `systematic_trading.data.fmp.FMPClient`, alongside Alpaca prices.

### Agents

`agents/` holds the LLM / tool-calling decision layer. Agents are plain Python — a strategy calls into one during `on_trading_iteration` to produce signals or sizing. Keep agents **broker-agnostic** so they run identically in backtest and live.

### Logging

`logging_setup.py` runs two channels so the console reads as a strategy narrative:
- **Framework (`lumibot`)** — quieted to WARNING, with a deny-list (`NOISE_SUBSTRINGS`) dropping known non-actionable startup warnings.
- **Strategy (`systematic_trading`)** — compact `HH:MM:SS | message` format via `get_logger(name)`.

Call `configure_logging()` once at startup (it's idempotent), after `import lumibot`, before `trader.run_all()`. Lumibot's telemetry JSON is disabled separately via `LUMIBOT_TELEMETRY=false` in `.env`.

## Configuration

`.env` is required (copy `.env.example`): Alpaca keys (broker + price feed), `ALPACA_PAPER` (defaults to true — live trading is opt-in), `FMP_API_KEY`, `LUMIBOT_TELEMETRY=false`.

All credential handling lives in `config.py` — **strategies and agents never read `os.environ` directly**. `config.py` calls `load_dotenv(override=False)` on import (real env vars win over `.env`, which is what CI/prod wants) and fails fast via `_require()` on missing keys. `alpaca_config()` returns the dict shape Lumibot's `Alpaca` broker expects.

## Safety rails (trading-specific)

- **Never default to real money.** Anything that touches order submission must keep paper as the default path; `ALPACA_PAPER=false` is an explicit user decision, never something code or docs flip silently.
- **Never run `uv run live` (or the `scripts/run_*` equivalents) yourself** unless the user explicitly asks — it opens a broker connection and can place orders. Backtests and `pytest` are safe to run freely.
- When changing order logic, trace the cash/position accounting by hand (sells → available cash → buys) before trusting a backtest that "looks fine".

## Response Type
- Please be clear, concise, and to the point in your responses and do your best to avoid unecessary verbosity

## Overall Goal of Code
- To write clean, clear, well architected code that is easy for humans to understand

## Development Guidelines

### Core Philosophy

- **KISS** — choose straightforward solutions; simple is easier to maintain and debug.
- **YAGNI** — implement only what's needed now, not what might be useful later.
- **DRY** — single source of truth for every piece of knowledge. Search for an existing helper before writing a new one; extract shared logic into pure reusable functions.

#### 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

#### 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.
- Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

#### 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

#### 4. Goal-Driven Execution

Define success criteria. Loop until verified.

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

### Design Principles

- **Dependency Inversion** — high-level modules depend on abstractions, not low-level modules.
- **Open/Closed** — open for extension, closed for modification.
- **Single Responsibility** — one clear purpose per function/class/module.
- **Fail Fast** — validate early, raise immediately when something's wrong.
- **Type safety** — type hints and explicit return types are mandatory; the codebase should read as self-documenting.
- **Resource efficiency** — context managers for all I/O; vectorize data-heavy work.

### Code Constraints

- Files: max 500 lines — split into modules if approaching the limit.
- Functions: max 50 lines, single responsibility.
- Classes: max 100 lines, one concept.
- Group code by feature/responsibility.

### Whitespace & Vertical Formatting (CRITICAL)

Code must breathe. Use blank lines to separate logical blocks within functions:

- Blank line after the initial declaration block.
- Blank line between distinct steps inside a loop (fetch → validate → transform → assign).
- Blank line before `return`.
- Blank line between independent `if` checks in a loop.

```python
def process_items(items: list[str], lookup: dict):
    results: dict[str, float] = {}
    errors: list[str] = []

    for item in items:
        value = lookup.get(item)

        if value is None:
            errors.append(item)
            continue

        transformed = value * 2.0

        results[item] = transformed

    return results, errors
```

### Naming

- Variables/functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private attributes: `_leading_underscore`
- Type aliases / Enums: `PascalCase` / `UPPER_SNAKE_CASE`
- Never prefix folders or files with `_`.

### Documentation

- Module docstring explaining purpose.
- Complete docstrings on public functions.
- **Preserve existing comments.** Do NOT delete or "clean up" inline comments that are already in the code — including short step-marker comments. Treat them as intentional. Only remove a comment if it is factually wrong after your change, and then replace it with a correct one rather than deleting it outright. This overrides any default tendency to strip "narration" comments.
- When editing a function, leave untouched comments exactly as they are unless the line they describe is itself being changed.
- Helper functions live at the **top** of the file under a banner block:

  ```
      ================================
  --> Helper funcs
      ================================
  ```

### Complexity Gauging

Before writing or planning: assess whether the approach is under-engineered, optimally engineered, or over-engineered. Aim for the middle.

### Testing

- No pytest scaffolding — write **real tests with real data**.
- A test exercises the full flow: pull real inputs, call the function, grade the output. Lint/format afterward.
- Don't create parallel `test_x.py` and `test_x_fixed.py` files — fix the one test in place.
- Trading-specific: tests must never place orders or hit the broker; a strategy change is verified by a backtest (`uv run backtest <name>`), whose tearsheet/stats in `logs/` are the ground truth.

### Hard Rules

- **No backwards-compatibility shims.** If a change is needed, build the new solution and update every caller. Backwards-compat violates the design principles.
- **Never create CLI flag–driven test scripts** like `tests/foo.py --mode long-only`. If behavior needs to switch, write separate entry points or pass arguments programmatically.
- **Never auto-create READMEs** for specific functionality unless explicitly requested.
- **Disagree freely** — correctness beats agreement. If the user is wrong, say so.
- For specs, standards, or patterns worth referencing later, write a document under `docs/`, organized by topic (e.g. `docs/strategies/`, `docs/data/`). Institutional knowledge belongs in the repo, not just chat history.
- **Agent system prompts use XML tags** (`<role>`, `<methodology>`, `<constraints>`, `<output_format>`) for top-level structure; markdown headers are sub-structure within those XML sections.
- Use the LSP / Pyright server when available.

### Branching

`main` (production) · `dev` (integration) · `feature/*` · `fix/*` · `refactor/*` · `docs/*` · `test/*`
