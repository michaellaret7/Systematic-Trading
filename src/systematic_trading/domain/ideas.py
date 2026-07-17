"""Trade-idea records and lifecycle types."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Literal

IdeaSide = Literal["long", "short"]
IdeaStatus = Literal["pending", "executed", "rejected"]

IDEA_SIDES: tuple[IdeaSide, ...] = ("long", "short")
IDEA_STATUSES: tuple[IdeaStatus, ...] = ("pending", "executed", "rejected")


@dataclass(frozen=True, slots=True)
class TradeIdea:
    """An actionable proposal before persistence or broker execution."""

    strategy: str
    ticker: str
    side: IdeaSide
    score: float
    allocation_pct: float
    thesis: str
    reference_price: float
    max_entry_price: float
    model: str
    created_at: datetime

    def __post_init__(self) -> None:
        """Reject malformed ideas at the domain boundary."""
        if not self.strategy.strip():
            raise ValueError("strategy must not be empty")

        if not self.ticker or self.ticker != self.ticker.strip().upper():
            raise ValueError("ticker must be a nonempty normalized symbol")

        if self.side not in IDEA_SIDES:
            raise ValueError(f"unknown side {self.side!r}; expected one of {IDEA_SIDES}")

        if not isfinite(self.score) or not 1 <= self.score <= 10:
            raise ValueError("score must be between 1 and 10")

        if not isfinite(self.allocation_pct) or not 0.5 <= self.allocation_pct <= 3:
            raise ValueError("allocation_pct must be between 0.5 and 3")

        if not self.thesis.strip():
            raise ValueError("thesis must not be empty")

        if not isfinite(self.reference_price) or self.reference_price <= 0:
            raise ValueError("reference_price must be positive")

        if not isfinite(self.max_entry_price) or self.max_entry_price <= 0:
            raise ValueError("max_entry_price must be positive")

        if not self.model.strip():
            raise ValueError("model must not be empty")

        if not isinstance(self.created_at, datetime):
            raise ValueError("created_at must be a datetime")
