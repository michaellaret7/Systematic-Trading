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

from systematic_trading.agents.tools.shared.fundamentals import get_fundamental_statement
from systematic_trading.agents.tools.shared.trade_ideas import submit_trade_idea
from systematic_trading.strategies.csf_champions.agents.ticker_analyst.mgmt_sub_agent import (
    MGMT_SUB_AGENT_CONFIG,
)
from systematic_trading.strategies.csf_champions.agents.ticker_analyst.moat_sub_agent import (
    MOAT_SUB_AGENT_CONFIG,
)
from systematic_trading.strategies.csf_champions.agents.ticker_analyst.prompt import SYSTEM
from systematic_trading.strategies.csf_champions.agents.ticker_analyst.risk_sub_agent import (
    RISK_SUB_AGENT_CONFIG,
)


STRATEGY = "csf_champions"
MODEL = "openai/gpt-5.6-sol"

ticker_analyst = Agent(
    provider="openrouter",
    model=MODEL,
    system=SYSTEM,
    tools=[
        get_fundamental_statement,
        # strategy/model are stamped onto every submitted idea; hidden from the LLM schema.
        bind_tool(submit_trade_idea, _strategy=STRATEGY, _model=MODEL),
    ],
    subagents=[
        MGMT_SUB_AGENT_CONFIG,
        MOAT_SUB_AGENT_CONFIG,
        RISK_SUB_AGENT_CONFIG,
    ],
)


if __name__ == "__main__":
    # Standalone test run: the harness reads env but never loads .env itself,
    # so the entry point loads it before the client is built.
    from dotenv import load_dotenv

    from agent_harness.sinks import LogSink

    load_dotenv()

    report = ticker_analyst.run(
        "Analyze (ticker: PAYP) and deliver your verdict.",
        sink=LogSink("ticker_analyst"),
    )

    print(report)
