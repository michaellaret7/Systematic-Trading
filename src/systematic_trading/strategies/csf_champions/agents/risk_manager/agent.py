from agent_harness.agent import Agent
from systematic_trading.strategies.csf_champions.agents.risk_manager.models import DrawdownDecision
from systematic_trading.strategies.csf_champions.agents.risk_manager.prompt import SYSTEM_PROMPT
from agent_harness.decorator import bind_tool
from systematic_trading.agents.shared_tools.trade_ideas import pull_trade_idea
from systematic_trading.strategies.csf_champions.agents.risk_manager.tools import run_screener
from systematic_trading.agents.shared_tools.fundamentals import get_fundamental_statement
from systematic_trading.agents.shared_tools.market_context import get_market_context
from systematic_trading.agents.shared_tools.prices import get_prices
from agent_harness.sinks import LogSink

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
            run_screener,
            get_fundamental_statement,
            get_prices,
            get_market_context,
            bind_tool(pull_trade_idea, _strategy=STRATEGY),
        ],
        output_model=DrawdownDecision,
    )


if __name__ == "__main__":
    agent = build_risk_manager()
    x = agent.run(task="pull the trade thesis for QLYS", sink=LogSink("tourka"))
    print(x)

