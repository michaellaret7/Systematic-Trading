# """Build the CSF Champions draft portfolio from pending trade ideas.

# Deterministic seeding, then agent shaping: pending ideas are deduped to the
# latest per ticker and split at ``MIN_SCORE`` — those at or above the cut seed
# the draft portfolio at their analyst's proposed weight, the rest stock the
# candidate bench. The portfolio-constructor agent then reviews the book,
# promotes bench names that earn a slot, and resizes or drops positions through
# its bound tools. No orders are placed; the finalized draft is returned for a
# later submission step.
# """

# from agent_harness.sinks import LogSink

# from systematic_trading.data.repository import load_ideas
# from systematic_trading.logging_setup import configure_logging, get_logger
# from systematic_trading.strategies.csf_champions.agents.portfolio_constructor.agent import (
#     STRATEGY,
#     bench,
#     portfolio,
#     portfolio_constructor,
# )
# from systematic_trading.strategies.csf_champions.portfolio import Holding, Portfolio

# MIN_SCORE = 7.0

# log = get_logger(__name__)


# def seed_portfolio(portfolio: Portfolio, bench: dict[str, Holding]) -> tuple[int, int]:
#     """Split pending ideas at MIN_SCORE: seed the book, stock the bench.

#     Ideas are deduped per ticker keeping the latest submission (``idea_id`` is
#     timestamp-prefixed, so lexicographic order is chronological). Returns the
#     number of seeded holdings and bench candidates.
#     """
#     ideas = load_ideas(STRATEGY, status="pending")

#     if ideas.empty:
#         return 0, 0

#     latest = ideas.sort_values(by="idea_id").drop_duplicates("ticker", keep="last")

#     for row in latest.to_dict("records"):
#         # DynamoDB returns numerics as Decimal — cast before comparing/storing.
#         holding = Holding(
#             idea_id=row["idea_id"],
#             ticker=row["ticker"],
#             side=row["side"],
#             score=float(row["score"]),
#             weight_pct=float(row["allocation_pct"]),
#             thesis=row["thesis"],
#             reference_price=float(row["reference_price"]),
#             max_entry_price=float(row["max_entry_price"]),
#         )

#         if holding.score >= MIN_SCORE:
#             portfolio.add(holding)
#         else:
#             bench[holding.ticker] = holding

#     return len(portfolio.holdings), len(bench)


# def build_portfolio() -> Portfolio:
#     """Seed the draft portfolio and bench, then run the constructor agent."""
#     seeded, benched = seed_portfolio(portfolio, bench)

#     if seeded == 0 and benched == 0:
#         log.warning("No pending ideas found — nothing to construct")
#         return portfolio

#     log.info(
#         "Seeded %d holdings (score >= %s) with %d bench candidates; running constructor",
#         seeded,
#         MIN_SCORE,
#         benched,
#     )

#     portfolio_constructor.run(
#         f"The draft portfolio has been seeded with {seeded} ideas at or above the conviction "
#         f"cut; {benched} below-cut ideas are on the bench. Review the book, promote any bench "
#         "names that earn a slot, and finalize it.",
#         sink=LogSink("portfolio_constructor"),
#     )

#     log.info("Draft portfolio finalized:\n%s", portfolio.summary())

#     return portfolio


# # if __name__ == "__main__":
# #     configure_logging()
# #     build_portfolio()
