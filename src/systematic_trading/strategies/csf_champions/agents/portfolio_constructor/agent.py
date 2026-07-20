"""Portfolio-constructor agent for the CSF Champions strategy.

The empty draft portfolio and candidate bench are created at import time
alongside the agent, and the portfolio tools are bound to those instances —
every tool call during a run reads and mutates the same in-memory state. The
build_portfolio workflow seeds both deterministically before the agent runs:
ideas at or above the cut go into the portfolio, the rest onto the bench for
the agent to promote from.

All are module-level singletons: one construction run per process (the agent
accumulates message history, and the portfolio carries seeded state).
"""

from agent_harness.agent import Agent
from agent_harness.base_tools.deploy_subagent import LogSink
from agent_harness.decorator import bind_tool

from systematic_trading.agents.tools.correlations import get_price_correlations
from systematic_trading.strategies.csf_champions.agents.portfolio_constructor.prompt import SYSTEM
from systematic_trading.strategies.csf_champions.agents.portfolio_constructor.tools import (
    add_position,
    drop_position,
    get_idea_thesis,
    get_portfolio_risk,
    set_position_weight,
    view_candidate_ideas,
    view_portfolio,
    view_sector_exposure,
)
from systematic_trading.strategies.csf_champions.portfolio import MIN_SCORE, Holding, Portfolio
from systematic_trading.data.repository import load_ideas, load_sector_tags

STRATEGY = "csf_champions"
MODEL = "openai/gpt-5.6-sol"


def seed_portfolio(portfolio: Portfolio, bench: dict[str, Holding]) -> tuple[int, int]:
    """Split pending ideas at MIN_SCORE: seed the book, stock the bench.

    Ideas are deduped per ticker keeping the latest submission (``idea_id`` is
    timestamp-prefixed, so lexicographic order is chronological). Returns the
    number of seeded holdings and bench candidates.
    """
    
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

        if holding.score >= MIN_SCORE:
            portfolio.add(holding)
        else:
            bench[holding.ticker] = holding

    return len(portfolio.holdings), len(bench)


portfolio = Portfolio()
bench: dict[str, Holding] = {}

seed_portfolio(portfolio, bench)

portfolio_constructor = Agent(
    model=MODEL,
    system=SYSTEM,
    tools=[
        bind_tool(view_portfolio, _portfolio=portfolio),
        bind_tool(view_sector_exposure, _portfolio=portfolio),
        bind_tool(get_portfolio_risk, _portfolio=portfolio, _bench=bench),
        bind_tool(view_candidate_ideas, _bench=bench),
        bind_tool(get_idea_thesis, _bench=bench, _portfolio=portfolio),
        bind_tool(add_position, _bench=bench, _portfolio=portfolio),
        bind_tool(set_position_weight, _portfolio=portfolio),
        bind_tool(drop_position, _portfolio=portfolio),
        get_price_correlations,
    ],
)

portfolio_constructor.run(SYSTEM, sink=LogSink("portfolio_constructor"))

print(portfolio.summary())
