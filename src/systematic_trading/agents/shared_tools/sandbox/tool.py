"""Agent tool: run Python against the full price and fundamentals repository.

Where the other shared tools answer one fixed question, this one lets the agent
ask its own — ranking the whole universe, building factor spreads, testing a
relationship across every filer — by writing code instead of calling a
pre-shaped endpoint. Execution is sandboxed; see ``runner`` for why that is the
boundary and not a convenience.

The snapshot is a daily file, so this is a research tool, not an execution one:
it cannot see today's bars and must never be the source of an order price.
"""

from typing import Annotated

from agent_harness.decorator import Param, agent_tool

from systematic_trading.agents.shared_tools.sandbox.runner import run_code

# Truncation ceiling on returned output. A stray `print(df)` over 1.7M rows
# would otherwise bury the agent's own context in bars it did not ask for.
MAX_OUTPUT_CHARS = 10_000

# Tail of a traceback handed back on failure. Enough for the agent to see the
# exception and the line that raised it without replaying the whole stack.
MAX_ERROR_CHARS = 2_000

DATA_LAYOUT = """
/data/prices.parquet             daily split-adjusted OHLCV, trailing 4 years
                                 (symbol, date, open, high, low, close, volume)
/data/fundamentals_panel.parquet built quarterly metrics panel, 130 columns —
                                 start here for screening and ranking
/data/{income,balance,cashflow,key_metrics,ratios}_{quarter,annual}.parquet
                                 raw FMP statements, for drilling into a name
"""


# ====================================
# --> Helper funcs
# ====================================


def _truncate(text: str, limit: int) -> str:
    """Clip text to ``limit`` characters, marking the cut so it is not mistaken for the end."""
    if len(text) <= limit:
        return text

    return f"{text[:limit]}\n... [truncated at {limit} characters]"


# ====================================
# --> Tool
# ====================================


@agent_tool(name="RunPython")
def run_python(
    code: Annotated[
        str,
        Param(
            description=(
                "Python source to execute. Print what you want returned — stdout is "
                "the only channel back, and nothing persists between calls. "
                "pandas, polars, numpy, pyarrow, duckdb, ta and scipy are installed; there is "
                "no network and no filesystem access outside the read-only /data mount. "
                f"Available files:\n{DATA_LAYOUT}\n"
                "Use duckdb for anything scanning the whole universe (it streams from "
                "disk and keeps memory flat), polars for grouped rolling work across the "
                "panel, and pandas when working on a few names. `ta` indicators take "
                "pandas Series, so convert with .to_pandas() if you built the frame in polars. "
                "Column names are discoverable at runtime with "
                "duckdb.sql(\"DESCRIBE SELECT * FROM '/data/fundamentals_panel.parquet'\")."
            )
        ),
    ],
) -> str:
    """
    Run Python code against the full price and fundamentals repository and
    return whatever it prints.

    Errors come back as text rather than raising, so a traceback can be read and
    the code corrected in a follow-up call. Data is a daily snapshot — use it for
    research, never as a price source for an order.
    """
    result = run_code(code)

    if result.timed_out:
        return "error: timed out — the code ran too long. Filter earlier or aggregate in duckdb."

    if result.oom_killed:
        return (
            "error: ran out of memory. Select only the columns you need, or use duckdb, "
            "which streams from disk instead of loading whole files."
        )

    if not result.ok:
        # Whatever printed before the exception is kept. A script that inspects
        # a schema and then fails on the next statement has already produced the
        # answer to its first question; discarding it costs a whole extra turn
        # re-running work that succeeded.
        partial = result.stdout.strip()
        prefix = f"{_truncate(partial, MAX_OUTPUT_CHARS)}\n\n" if partial else ""

        return (
            f"{prefix}error: exit code {result.exit_code}\n"
            f"{_truncate(result.stderr, MAX_ERROR_CHARS)}"
        )

    output = result.stdout.strip()

    if not output:
        return "error: the code printed nothing — print the result you want returned."

    return _truncate(output, MAX_OUTPUT_CHARS)
