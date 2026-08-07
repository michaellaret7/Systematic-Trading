"""Structured output types for the CSF Champions capital-reallocator agent."""

from pydantic import BaseModel, Field


class ReallocationPick(BaseModel):
    """One long replacement the reallocator wants to fund."""

    ticker: str
    weight_pct: float = Field(
        description="Account weight percentage for the new long (0.5-3.0).",
        ge=0.5,
        le=3.0,
    )
    reason: str


class ReallocationPlan(BaseModel):
    """Agent verdict: zero or more replacement longs (empty = hold cash)."""

    picks: list[ReallocationPick] = Field(default_factory=list)
