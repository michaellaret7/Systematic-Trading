"""Structured output types for the CSF Champions risk-manager agent."""

from typing import Literal

from pydantic import BaseModel, Field

DrawdownAction = Literal["hold", "trim", "exit", "add"]

# Fraction of current position size that an "add" may size up to.
# Shared by the agent prompt and submit_drawdown_orders validation.
MAX_ADD_AMOUNT = 0.75


class DrawdownDecision(BaseModel):
    """Risk-manager verdict for one drawdown review."""

    ticker: str
    action: DrawdownAction
    reason: str
    amount: float | None = Field(
        default=None,
        description="Required when action is add or trim",
    )
