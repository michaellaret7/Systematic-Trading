"""Capital-reallocator agent for the CSF Champions strategy.

Built fresh per reallocation run (``Agent`` keeps message history). Live-book
tools bind to the caller's Lumibot strategy; shared research tools are unbound.
``run()`` returns a ``ReallocationPlan`` via structured output — the workflow
sizes picks into buys; this agent never submits orders.
"""

from agent_harness.agent import Agent
from agent_harness.decorator import bind_tool
from lumibot.strategies import Strategy

from systematic_trading.agents.shared_tools.correlations import get_price_correlations
from systematic_trading.agents.shared_tools.fundamentals import get_fundamental_statement
from systematic_trading.agents.shared_tools.market_context import get_market_context
from systematic_trading.agents.shared_tools.prices import get_prices
from systematic_trading.agents.shared_tools.screeners import csf_screener_tool
from systematic_trading.agents.shared_tools.trade_ideas import pull_trade_idea
from systematic_trading.strategies.csf_champions.agents.cptl_reallocator.models import (
    ReallocationPlan,
)
from systematic_trading.strategies.csf_champions.agents.cptl_reallocator.prompt import (
    SYSTEM_PROMPT,
)
from systematic_trading.strategies.csf_champions.agents.cptl_reallocator.tools import (
    get_candidate_fit,
    view_live_book,
    view_sector_exposure,
)

MODEL = "openai/gpt-5.6-sol"
STRATEGY = "csf_champions"


def build_cptl_reallocator(strategy: Strategy) -> Agent:
    """Construct a capital-reallocator bound to the live strategy book.

    ``run()`` returns a ``ReallocationPlan`` via ``output_model`` parsing.
    """
    return Agent(
        model=MODEL,
        system=SYSTEM_PROMPT,
        tools=[
            bind_tool(view_live_book, _strategy=strategy),
            bind_tool(view_sector_exposure, _strategy=strategy),
            bind_tool(get_candidate_fit, _strategy=strategy),
            bind_tool(pull_trade_idea, _strategy=STRATEGY),
            csf_screener_tool,
            get_fundamental_statement,
            get_market_context,
            get_prices,
            get_price_correlations,
        ],
        output_model=ReallocationPlan,
    )
