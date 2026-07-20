"""Parent ticker-analyst agent for the CSF Champions strategy.

Given one screened ticker, the agent deploys the management / moat / risk
sub-agents for qualitative research, runs the fundamental deep-dive itself
via GetFundamentalStatement, and synthesizes everything into a BUY / WATCH /
PASS verdict (see prompt.SYSTEM).

Message history accumulates across run() calls on one instance — the batch
runner must construct a fresh Agent per ticker rather than reusing this one.
"""

from agent_harness.agent import Agent
from agent_harness.decorator import bind_tool

from systematic_trading.agents.tools.fundamentals import get_fundamental_statement
from systematic_trading.agents.tools.prices import get_recent_prices
from systematic_trading.agents.tools.trade_ideas import submit_trade_idea
from systematic_trading.strategies.csf_champions.agents.ticker_analyst.prompt import SYSTEM
from systematic_trading.strategies.csf_champions.agents.ticker_analyst.subagents.management import (
    MANAGEMENT_SUBAGENT_CONFIG,
)
from systematic_trading.strategies.csf_champions.agents.ticker_analyst.subagents.moat import (
    MOAT_SUBAGENT_CONFIG,
)
from systematic_trading.strategies.csf_champions.agents.ticker_analyst.subagents.risk import (
    RISK_SUBAGENT_CONFIG,
)

STRATEGY = "csf_champions"
MODEL = "openai/gpt-5.6-sol"

def build_ticker_analyst() -> Agent:
    """Construct a fresh ticker-analyst agent.

    `Agent` accumulates message history across `run()` calls, so batch runners
    must build one instance per ticker (and per thread) rather than sharing a
    singleton — see the module docstring.
    """
    return Agent(
        provider="openrouter",
        model=MODEL,
        system=SYSTEM,
        tools=[
            get_fundamental_statement,
            get_recent_prices,
            # strategy/model are stamped onto every submitted idea; hidden from the LLM schema.
            bind_tool(submit_trade_idea, _strategy=STRATEGY, _model=MODEL),
        ],
        subagents=[
            MANAGEMENT_SUBAGENT_CONFIG,
            MOAT_SUBAGENT_CONFIG,
            RISK_SUBAGENT_CONFIG,
        ],
    )

