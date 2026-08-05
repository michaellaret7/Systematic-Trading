from agent_harness.agent import Agent
from agent_harness.decorator import bind_tool
from agent_harness.sinks import LogSink

from systematic_trading.agents.shared_tools.fundamentals import get_fundamental_statement
from systematic_trading.agents.shared_tools.market_context import get_market_context
from systematic_trading.agents.shared_tools.prices import get_prices
from systematic_trading.agents.shared_tools.trade_ideas import pull_trade_idea
from systematic_trading.strategies.csf_champions.agents.risk_manager.models import DrawdownDecision
from systematic_trading.strategies.csf_champions.agents.risk_manager.prompt import SYSTEM_PROMPT
from systematic_trading.strategies.csf_champions.agents.risk_manager.subagents.macro import (
    MACRO_SUBAGENT_CONFIG,
)
from systematic_trading.strategies.csf_champions.agents.risk_manager.subagents.ticker_research import (
    TICKER_RESEARCH_SUBAGENT_CONFIG,
)
from systematic_trading.strategies.csf_champions.agents.risk_manager.tools import run_screener

MODEL = "openai/gpt-5.6-sol"
STRATEGY = "csf_champions"


def build_risk_manager() -> Agent:
    """Construct a fresh risk-manager agent (one instance per ticker review).

    ``run()`` returns a ``DrawdownDecision`` via ``output_model`` structured parsing.
    """

    return Agent(
        model=MODEL,
        system=SYSTEM_PROMPT,
        tools=[
            get_fundamental_statement,
            get_prices,
            get_market_context,
            bind_tool(pull_trade_idea, _strategy=STRATEGY),
        ],
        subagents=[
            TICKER_RESEARCH_SUBAGENT_CONFIG,
            MACRO_SUBAGENT_CONFIG,
        ],
        output_model=DrawdownDecision,
    )
