"""Structured output types for the CSF Champions risk-manager agent."""

from typing import Literal

from pydantic import BaseModel, Field

DrawdownAction = Literal["hold", "trim", "exit", "add"]


class DrawdownDecision(BaseModel):
    """Risk-manager verdict for one drawdown review."""

    ticker: str
    action: DrawdownAction
    reason: str
    amount: float | None = Field(
        default=None,
        description="Required when action is add or trim",
    )
