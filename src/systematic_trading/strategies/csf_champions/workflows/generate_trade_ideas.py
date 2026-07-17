"""Generate CSF Champions trade ideas from screened candidates.

Screens the CSF Champions universe, takes the top names, and runs the
ticker-analyst agent over them with bounded concurrency — `MAX_WORKERS`
agents in flight at once, the next ticker starting the instant one finishes.

The run stops early once `TARGET_IDEAS` ideas have been submitted this run
(candidates are analyzed in screen-rank order, so the tail adds the least);
otherwise it works through all `TOP_N`. In-flight agents finish when the
target hits, so the final idea count can overshoot by up to `MAX_WORKERS`.

Each agent persists its own verdict via `submit_trade_idea`; this workflow is
fire-and-forget, logging only per-ticker success/failure.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from agent_harness.sinks import LogSink

from systematic_trading.data.repository import count_ideas_since
from systematic_trading.logging_setup import get_logger
from systematic_trading.strategies.csf_champions.agents.ticker_analyst.agent import (
    STRATEGY,
    build_ticker_analyst,
)
from systematic_trading.strategies.csf_champions.screening import screen

TOP_N = 10
TARGET_IDEAS = 85
MAX_WORKERS = 7

log = get_logger(__name__)


def analyze_candidate(symbol: str) -> None:
    """Run a fresh ticker-analyst agent over one ticker to its verdict."""
    agent = build_ticker_analyst()

    agent.run(
        f"Analyze (ticker: {symbol}) and deliver your verdict.",
        sink=LogSink(f"ticker_analyst_{symbol}"),
    )


def generate_trade_ideas() -> None:
    """Screen and analyze the highest-ranked CSF Champions candidates."""
    ranked = screen()
    symbols = ranked["symbol"].tolist()[:TOP_N]
    run_start = datetime.now(timezone.utc)

    log.info("Analyzing %d tickers with %d concurrent agents", len(symbols), MAX_WORKERS)

    done = 0
    failed = 0
    target_hit = False

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(analyze_candidate, symbol): symbol for symbol in symbols}

        for future in as_completed(futures):
            symbol = futures[future]

            if future.cancelled():
                continue

            try:
                future.result()
                done += 1
                log.info("[%d/%d] %s done", done + failed, len(symbols), symbol)

            except Exception as exc:
                failed += 1
                log.error("[%d/%d] %s failed: %s", done + failed, len(symbols), symbol, exc)

            if target_hit:
                continue

            ideas = count_ideas_since(STRATEGY, run_start)

            if ideas >= TARGET_IDEAS:
                target_hit = True
                log.info(
                    "Idea target reached (%d/%d) — cancelling remaining tickers",
                    ideas,
                    TARGET_IDEAS,
                )
                # In-flight agents finish and are logged; unstarted tickers are dropped.
                pool.shutdown(wait=False, cancel_futures=True)

    log.info("Batch complete: %d succeeded, %d failed", done, failed)

# in the strategy class
# if ideas_generated = True, pull from dynamodb 
# if ideas_generated = False, generate new ideas, pull from dynamodb

if __name__ == "__main__":
    generate_trade_ideas()