"""Drawdown risk-manager agent for CSF Champions."""

from systematic_trading.strategies.csf_champions.agents.risk_manager.agent import (
    build_risk_manager,
)
from systematic_trading.strategies.csf_champions.agents.risk_manager.models import (
    DrawdownAction,
    DrawdownDecision,
)

__all__ = [
    "DrawdownAction",
    "DrawdownDecision",
    "build_risk_manager",
]
