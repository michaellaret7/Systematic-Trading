# TODO: BUILD THE ACTIVE MANAGER AGENT
# Decide tools abd subagents for this agent.

from agent_harness.agent import Agent

from systematic_trading.strategies.csf_champions.agents.risk_manager.models import (
    DrawdownDecision,
)


def build_risk_manager() -> Agent:
    """Construct a fresh risk-manager agent (one instance per ticker review).

    ``run()`` returns a ``DrawdownDecision`` via ``output_model`` structured parsing.
    """
    # TODO: model, system prompt, tools, and subagents
    return Agent(
        output_model=DrawdownDecision,
    )
