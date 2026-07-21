"""Build the CSF Champions draft portfolio from pending trade ideas.

Deterministic seeding, then agent shaping: pending ideas are deduped to the
latest per ticker and split at ``MIN_SCORE`` — those at or above the cut seed
the caller's portfolio at their analyst's proposed weight, the rest stock the
candidate bench. The portfolio-constructor agent then reviews the book,
promotes bench names that earn a slot, and resizes or drops positions through
its bound tools. No orders are placed; the caller's portfolio instance holds
the finalized draft for a later submission step.
"""

from agent_harness.sinks import LogSink

from systematic_trading.data.repository import load_ideas, load_sector_tags
from systematic_trading.logging_setup import get_logger
from systematic_trading.strategies.csf_champions.agents.portfolio_constructor.agent import (
    STRATEGY,
    build_portfolio_constructor,
)
from systematic_trading.strategies.csf_champions.portfolio import MIN_SCORE, Holding, Portfolio

log = get_logger(__name__)


#     ================================
# --> Helper funcs
#     ================================


def seed_portfolio(portfolio: Portfolio, bench: dict[str, Holding]) -> tuple[int, int]:
    """Split pending ideas at MIN_SCORE: seed the book, stock the bench.

    Ideas are deduped per ticker keeping the latest submission (``idea_id`` is
    timestamp-prefixed, so lexicographic order is chronological). Returns the
    number of seeded holdings and bench candidates.
    """

    # This is where we access the DynamoDB table and get all of the trade ideas from first step of the init pipeline
    ideas = load_ideas(STRATEGY, status="pending")

    if ideas.empty:
        return 0, 0

    latest = ideas.sort_values(by="idea_id").drop_duplicates("ticker", keep="last")

    # One panel read tags every holding; missing symbols degrade to "Unknown".
    tags = load_sector_tags()

    for row in latest.to_dict("records"):
        tag = tags.get(row["ticker"], {"sector": "Unknown", "industry": "Unknown"})

        # DynamoDB returns numerics as Decimal — cast before comparing/storing.
        holding = Holding(
            idea_id=row["idea_id"],
            ticker=row["ticker"],
            sector=tag["sector"],
            industry=tag["industry"],
            side=row["side"],
            score=float(row["score"]),
            weight_pct=float(row["allocation_pct"]),
            thesis=row["thesis"],
            reference_price=float(row["reference_price"]),
            max_entry_price=float(row["max_entry_price"]),
        )

        # If the idea has a score of over 7, we add it to the portfolio automatically
        if holding.score >= MIN_SCORE:
            portfolio.add(holding)
        else:
            # If the idea has a score of less than 7, we add it to the bench
            bench[holding.ticker] = holding

    return len(portfolio.holdings), len(bench)


def construct_portfolio(portfolio: Portfolio) -> None:
    """Seed the caller's portfolio and bench, then run the constructor agent.

    Mutates ``portfolio`` in place so the caller's instance carries the
    finalized draft.
    """
    bench: dict[str, Holding] = {}

    # Seed the initial Portfolio() cls object with the trade ideas from the DynamoDB table over a score cutoff of 7
    # and the trade ideas with a score of less than 7 are added to the bench dict above
    seeded, benched = seed_portfolio(portfolio, bench)

    if seeded == 0 and benched == 0:
        log.warning("No pending ideas found — nothing to construct")
        return

    log.info(
        "Seeded %d holdings (score >= %s) with %d bench candidates; running constructor",
        seeded,
        MIN_SCORE,
        benched,
    )

    constructor = build_portfolio_constructor(portfolio, bench)

    # Run the portfolio constructor agent to build the portfolio and append it to the portfolio object
    constructor.run(
        f"The draft portfolio has been seeded with {seeded} ideas at or above the conviction "
        f"cut; {benched} below-cut ideas are on the bench. Review the book, promote any bench "
        "names that earn a slot, and finalize the portfolio.",
        sink=LogSink("portfolio_constructor"),
    )

    # Log the final portfolio summary
    log.info("Draft portfolio finalized:\n%s", portfolio.summary())
