"""Order records shared by strategies and the trade ledger."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite


@dataclass(frozen=True, slots=True)
class TradeOrder:
    """One submitted entry order before persistence in the trade ledger.

    ``target_quantity`` is the full intended position size; fills accumulate
    against it in the ledger, possibly across several trading days.
    ``limit_price`` is what this order was priced at; a re-submit prices itself
    from the market at the time, so nothing else needs to ride along.
    ``idea_id`` links back to the trade idea this order executes — the ledger
    row is the single source of truth for that link.
    """

    strategy: str
    idea_id: str
    symbol: str
    side: str
    target_quantity: int
    limit_price: float
    submitted_at: datetime

    def __post_init__(self) -> None:
        """Reject malformed orders at the domain boundary."""
        if not self.strategy.strip():
            raise ValueError("strategy must not be empty")

        if not self.idea_id.strip():
            raise ValueError("idea_id must not be empty")

        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be a nonempty normalized symbol")

        if not self.side.strip():
            raise ValueError("side must not be empty")

        if self.target_quantity <= 0:
            raise ValueError("target_quantity must be positive")

        if not isfinite(self.limit_price) or self.limit_price <= 0:
            raise ValueError("limit_price must be positive")

        if not isinstance(self.submitted_at, datetime):
            raise ValueError("submitted_at must be a datetime")
