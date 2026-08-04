"""Drawdown risk-manager agent for CSF Champions."""

from systematic_trading.strategies.csf_champions.agents.risk_manager.agent import (
    build_risk_manager,
)
from systematic_trading.strategies.csf_champions.agents.risk_manager.models import (
    MAX_ADD_AMOUNT,
    DrawdownAction,
    DrawdownDecision,
)

__all__ = [
    "MAX_ADD_AMOUNT",
    "DrawdownAction",
    "DrawdownDecision",
    "build_risk_manager",
]
