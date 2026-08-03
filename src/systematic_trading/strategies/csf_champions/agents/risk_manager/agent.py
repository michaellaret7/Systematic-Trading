# TODO: BUILD THE ACTIVE MANAGER AGENT
# Decide tools abd subagents for this agent.

from agent_harness.agent import Agent
from systematic_trading.strategies.csf_champions.agents.risk_manager.models import DrawdownDecision
from systematic_trading.strategies.csf_champions.agents.risk_manager.prompt import SYSTEM_PROMPT
from agent_harness.decorator import bind_tool
from systematic_trading.agents.shared_tools.trade_ideas import pull_trade_idea
from systematic_trading.strategies.csf_champions.agents.risk_manager.tools import run_screener
from systematic_trading.agents.shared_tools.drawdown import get_drawdown_profile
from systematic_trading.agents.shared_tools.fundamentals import get_fundamental_statement
from systematic_trading.agents.shared_tools.prices import get_prices_with_technicals
from systematic_trading.agents.shared_tools.relative_strength import get_relative_strength
from agent_harness.sinks import LogSink

MODEL = "openai/gpt-5.6-sol"
STRATEGY = "csf_champions"
SYSTEM_PROMPT = """
You are a risk manager for a trading strategy.
You are responsible for reviewing drawdowns in the portfolio and deciding whether to sell the position.
"""


def build_risk_manager() -> Agent:
    """Construct a fresh risk-manager agent (one instance per ticker review).

    ``run()`` returns a ``DrawdownDecision`` via ``output_model`` structured parsing.
    """

    return Agent(
        model=MODEL,
        system=SYSTEM_PROMPT,
        tools=[
            run_screener,
            get_fundamental_statement,
            get_prices_with_technicals,
            get_drawdown_profile,
            get_relative_strength,
            bind_tool(pull_trade_idea, _strategy=STRATEGY),
        ],
        output_model=DrawdownDecision,
    )


if __name__ == "__main__":
    agent = build_risk_manager()
    x = agent.run(task="pull the trade thesis for QLYS", sink=LogSink("tourka"))
    print(x)
