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

from systematic_trading.data.providers.fmp import FMPClient
from systematic_trading.data.repository import count_ideas_since
from systematic_trading.logging_setup import configure_logging, get_logger
from systematic_trading.strategies.csf_champions.agents.ticker_analyst.agent import (
    STRATEGY,
    build_ticker_analyst,
)
from systematic_trading.strategies.csf_champions.screening import screen

TOP_N = 200
TARGET_IDEAS = 85
MAX_WORKERS = 7

# Universe listings for the symbol -> company-name map. The floor sits below the
# universe's $2bn cutoff so names survive market-cap drift between panel builds.
EXCHANGES = "NASDAQ,NYSE,AMEX"
NAME_MARKET_CAP_FLOOR = 1_000_000_000

log = get_logger(__name__)


def company_names(symbols: list[str]) -> dict[str, str]:
    """Map each candidate symbol to its company name via one FMP screener call.

    Tickers collide across exchanges (AERO, IAG, ...), so agents need the full
    company name to research the right business. Symbols missing from the
    screener response fall back to a ticker-only prompt.
    """
    listings = FMPClient().screener(
        market_cap_more_than=NAME_MARKET_CAP_FLOOR,
        exchange=EXCHANGES,
    )
    names = dict(zip(listings["symbol"], listings["companyName"]))

    return {symbol: names[symbol] for symbol in symbols if symbol in names}


def analyze_candidate(symbol: str, name: str | None) -> None:
    """Run a fresh ticker-analyst agent over one ticker to its verdict."""
    agent = build_ticker_analyst()

    task = (
        f"Analyze (ticker: {symbol}, company: {name}) and deliver your verdict."
        if name
        else f"Analyze (ticker: {symbol}) and deliver your verdict."
    )

    agent.run(
        task,
        sink=LogSink(f"analyst_{symbol}"),
    )


def generate_trade_ideas() -> None:
    """Screen and analyze the highest-ranked CSF Champions candidates."""
    ranked = screen()
    symbols = ranked["symbol"].tolist()[:TOP_N]
    names = company_names(symbols)
    run_start = datetime.now(timezone.utc)

    log.info("Analyzing %d tickers with %d concurrent agents", len(symbols), MAX_WORKERS)

    if len(names) < len(symbols):
        log.warning("No company name for: %s", ", ".join(s for s in symbols if s not in names))

    done = 0
    failed = 0
    target_hit = False

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(analyze_candidate, symbol, names.get(symbol)): symbol for symbol in symbols
        }

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
    configure_logging()
    generate_trade_ideas()
