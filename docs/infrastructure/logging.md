# Logging

One log line format for the whole system, regardless of which subsystem emitted it.

## Problem

A live run emits four formats from four independent logger trees:

```
15:47:13 | Analyzing 47 tickers with 8 concurrent agents                 systematic_trading
2026-07-22 15:47:13,923 | INFO | [CsfChampions] Order was filled: ...    lumibot
15:46:54 INFO  agent.portfolio_constructor: turn.end iters=7 tools=97    agent        (agent_harness LogSink)
sink LangfuseSink.on_turn_end raised: ...                                agent_harness (bare, via lastResort)
```

Nothing can sort, scan, or parse that with one rule — and the S3 archive and any future
live subscriber inherit the mess.

## Design

All four trees already produce `logging.LogRecord`s, so there is nothing to funnel or
wrap. **One handler on the root logger** formats everything that propagates up to it.

```
systematic_trading ─┐
agent              ─┼─> root: StreamHandler + _UnifiedFormatter + _NoiseFilter ──> stdout
agent_harness      ─┤
lumibot            ─┘   (its own handler is filtered dead; records propagate)
```

| Logger | Level | Handler | Propagate |
|---|---|---|---|
| root | `WARNING` | ours — the only one that writes | — |
| `systematic_trading` | `INFO` | none | `True` |
| `agent` | `INFO` | none — cleared, see below | `True` |
| `agent_harness` | inherits `WARNING` | none | `True` |
| `lumibot` | `LUMIBOT_LOG_LEVEL` | its own, reject-filtered | `True` (lumibot forces this) |

Root's `WARNING` is the default for every unconfigured tree — httpx, botocore, langfuse
SDK — so third-party INFO stays out without naming any of them. It does not gate our
trees: ancestor logger levels are never re-checked during propagation, only handler levels.

Lumibot keeps its handler because it re-adds one whenever the list is empty
(`lumibot_logger.py:700-705`). A reject-all **filter** neutralizes it instead; lumibot
never touches `handler.filters`. Its records then reach root like everyone else's.

## Record format

```
HH:MM:SS | LEVEL    | source               | message
```

```
15:46:30 | INFO     | analyst_LVS          | tool.start GetFundamentalStatement()
15:47:13 | INFO     | enter_positions      | LVS: buy 164 @ limit $45.29 (target 2.10%)
15:47:13 | INFO     | broker               | Order was filled: 164 LVS buy @ $45.29
15:47:44 | WARNING  | enter_positions      | MSFT: no price available — skipping entry
```

| Column | Width | Rule |
|---|---|---|
| time | 8 | `%H:%M:%S`. The date lives in the S3 filename. |
| level | 8 | Full name — `INFO`, `DEBUG`, `WARNING`, `ERROR`, `CRITICAL`. Never abbreviated. |
| source | 20 | Derived from `record.name`; truncated at 20. |
| message | — | Stripped, then verbatim. |

### Source derivation

Last dotted segment of the logger name, with three adjustments:

- **`agent.` tree** — the whole name after `agent.` is tagged `_agent`, so an agent line
  is obvious at a glance. The full remainder is used (not the last segment) so dotted
  tickers survive.
- **Generic last segment** (`strategy`, `agent`) — the segment before it is used instead,
  so every strategy doesn't collapse to `strategy` (`live.py` accepts `nargs="+"`).
- **Leading underscore** — stripped, so framework private modules read cleanly.

| Logger name | Source |
|---|---|
| `systematic_trading…workflows.enter_positions` | `enter_positions` |
| `systematic_trading…csf_champions.strategy` | `csf_champions` |
| `lumibot.brokers.broker` | `broker` |
| `lumibot.strategies._strategy` | `strategy` |
| `agent.constructor` | `constructor_agent` |
| `agent.analyst_LVS` | `analyst_LVS_agent` |
| `agent.analyst_BRK.B` | `analyst_BRK.B_agent` |
| `agent_harness.sinks.langfuse` | `langfuse` |

Agent sink names are set **at the call site**; the `_agent` tag and cleanup happen in the
formatter, so the raw logger names stay clean for filtering
(`logging.getLogger("agent.analyst_LVS")`):

```python
LogSink(f"analyst_{symbol}")   # generate_trade_ideas.py — was ticker_analyst_{symbol}
LogSink("constructor")         # build_portfolio.py       — was portfolio_constructor
```

Underscore, not `analyst[{symbol}]`: brackets are regex metacharacters, and the `agent.`
rule keeps dotted tickers intact rather than splitting `BRK.B`.

`live.py` and `backtest.py` currently log on the root app logger directly, which would
render as source `systematic_trading`. Give them `get_logger("live")` / `get_logger("backtest")`.

### Multi-line records

Continuation lines are indented to the message column:

```
15:46:54 | INFO     | build_portfolio      | Draft portfolio finalized:
                                           | LVS    2.10%   $7,427   164 sh
```

**Parser rule:** a line matching `^\d\d:\d\d:\d\d \| ` starts a record; anything else
continues the one above it.

This is a common path, not an edge case. Sources:

- **Agent tool args** — `helpers.py:18` truncates string args to 80 chars without stripping newlines.
- **Agent tool errors** — `helpers.py:73-77` keeps 200 chars of raw payload, so every ERROR `tool.end` may carry a traceback.
- **Lumibot** — e.g. `brokers/alpaca.py:606`, and the socket-stream startup warning.

The formatter must `.strip()` each message itself. Lumibot used to do this
(`lumibot_logger.py:537-542`) and no longer runs in this path; without it, trailing
newlines produce blank continuation lines.

**Interleaving cannot corrupt this.** `MAX_WORKERS` analysts log concurrently, and
interleaved continuation lines would silently attach to the wrong record. One handler
means one lock: `Handler.handle` holds it and `StreamHandler.emit` does a single
`write()`. Any future handler must preserve that.

### Levels

Same taxonomy across all trees, so a level means one thing regardless of source.

| Level | Meaning | `systematic_trading` | `agent` |
|---|---|---|---|
| `INFO` | Narrative. | `Open-order sweep: 3 open, 1 healed, 2 re-submitted` | `tool.end GetRecentPrices 1.8s` |
| `WARNING` | Degraded, continuing. | `MSFT: buys zero whole shares — skipping` | `tool.end SubmitTradeIdea denied` |
| `ERROR` | A unit of work failed. | `[12/47] LVS failed: RateLimitError` | `tool.end GetFundamentals error: 404` |
| `CRITICAL` | Nothing special today. Lumibot's emergency shutdown fires only when `LOG_ERRORS_TO_CSV` is set, which it is not. | — | — |

`agent` spans all three deliberately (`log.py:185-190`): tool `error` → ERROR,
`denied`/`interrupted` → WARNING, otherwise INFO. Everything stays at its emitted level —
maximum observability into agent runs is the goal.

**Volume:** `agent` is the loudest tree by an order of magnitude. One
`portfolio_constructor` run reported `iters=7 tools=97` ≈ 205 lines; ticker analysts run
`MAX_WORKERS`-concurrent across ~50 symbols on top of that.

**A failing ticker yields two ERROR lines at different granularities.** `tool.end … error`
is per-call and usually recovered; `generate_trade_ideas.py` fires `[12/47] LVS failed`
only when the whole ticker throws. Both are wanted — do not dedupe.

## Gotchas

**Lumibot reverts `setLevel`.** Every `get_logger()` re-runs `_apply_levels`
(`lumibot_logger.py:713-716`), resetting both logger and handler level from
`LUMIBOT_LOG_LEVEL` (default `INFO`, read fresh each call, `:656`). The env var is the
only durable knob — and it is ignored in backtests, where `BACKTESTING_QUIET_LOGS`
defaults true and pins lumibot to `ERROR` (`:662-676`). Lumibot is effectively silent
below ERROR in backtests; that is fine.

Lumibot stays at `INFO` in live deliberately — `Order was filled` (`broker.py:2620`) is a
real portfolio event with no way to get it at `WARNING`. `NOISE_SUBSTRINGS` suppresses
the known-useless startup lines. `StrategyLoggerAdapter` bakes `[CsfChampions]` into the
message text (`:592`); left in place for now.

**`_NoiseFilter` must live on a handler.** A logger's filters run only for records logged
directly on it — `callHandlers` collects ancestor *handlers*, never ancestor filters. On
the `lumibot` logger it would silently match nothing, since every noise message comes
from a child (`lumibot.brokers.alpaca`, `lumibot.strategies._strategy`).

**`agent_harness` must be repaired, not ordered around.** `LogSink.__init__` bootstraps
only `if not self.log.hasHandlers()` (`log.py:97`), so a root handler makes it defer. But
if a `LogSink` is constructed first it clears `agent`'s handlers, attaches a stderr
handler, and sets `propagate = False` (`log.py:64-71`). `configure_logging()` therefore
clears `agent`'s handlers and forces `propagate = True` rather than documenting a call
order.

**`configure_logging()` must run after `import lumibot`.** Lumibot's first-time config
removes existing handlers from its own logger. Today this holds — `live.py` and
`backtest.py` import lumibot before calling it, and the pod job path pulls it in
transitively — but it is invisible and load-bearing.

**The first lines of every log are unformattable.** Lumibot prints its banner and
`.env` notice through its own handler at import, before `configure_logging()` exists.
Those lines will not match the parser rule.

## Out of scope

**The memory monitor** (`cloud/bootstrap.py:32`) samples cgroup usage from bash every 30s
and appends straight to the log. It keeps its own format on purpose: it must keep
sampling when Python is wedged or being OOM-killed, which is the entire reason it exists.

**Pod bootstrap output** (`apt-get`, `git clone`, `uv sync`) predates the Python process.

## Module

`logging_setup.py`, ~150 lines. Notably it does **not** import lumibot — the root-handler
design needs no `LumibotFormatter` subclass, so `get_logger()` stays usable from `data/`
and `scripts/` without booting the framework.

- `_UnifiedFormatter(logging.Formatter)` — the single definition of a log line
- `_NoiseFilter` — on our root handler
- `_RejectAll` — on lumibot's handler
- `configure_logging()` — idempotent; wires root, repairs `agent`, filters lumibot
- `get_logger()` — unchanged

## Future

**Structured agent events.** `turn.end` flattens real data into prose
(`in=706259 out=12116 cached=623043 cost=$1.1064`). Our own `Sink` against
`agent_harness`'s 16-method protocol would emit those as fields via `extra={…}`. Worth
doing when something consumes cost per run.

**Transport.** The formatter is independent of destination, so an S3 or pub-sub handler
needs no format change — the point of settling this first. Two caveats when that lands:
lumibot's `colored()` output (`broker.py:2620`) carries ANSI codes whenever stdout is a
tty, and a *second* root handler will double-print lumibot records, since lumibot forces
`propagate = True` on its own logger while our trees will have it too.
