"""Portfolio-constructor agent for the CSF Champions strategy.

The agent is constructed per run with its portfolio tools bound to the
caller's portfolio and bench — every tool call during a run reads and mutates
those instances, so the shaped book survives after the agent finishes.
``Agent`` accumulates message history across ``run()`` calls, so callers build
a fresh instance per construction run rather than sharing a singleton.
"""

from agent_harness.agent import Agent
from agent_harness.decorator import bind_tool

from systematic_trading.agents.tools.correlations import get_price_correlations
from systematic_trading.strategies.csf_champions.agents.portfolio_constructor.prompt import SYSTEM
from systematic_trading.strategies.csf_champions.agents.portfolio_constructor.tools import (
    add_position,
    demote_to_bench,
    get_idea_thesis,
    get_portfolio_risk,
    reject_idea,
    set_position_weight,
    submit_portfolio,
    view_candidate_ideas,
    view_portfolio,
    view_sector_exposure,
)
from systematic_trading.strategies.csf_champions.portfolio import Holding, Portfolio

STRATEGY = "csf_champions"
MODEL = "openai/gpt-5.6-sol-pro"

def build_portfolio_constructor(portfolio: Portfolio, bench: dict[str, Holding]) -> Agent:
    """Construct a portfolio-constructor agent bound to the given book and bench."""
    return Agent(
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
            bind_tool(reject_idea, _bench=bench, _portfolio=portfolio),
            bind_tool(demote_to_bench, _bench=bench, _portfolio=portfolio),
            bind_tool(submit_portfolio, _portfolio=portfolio),
            get_price_correlations,
        ],
    )
