"""Order records shared by strategies and the trade ledger."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite


@dataclass(frozen=True, slots=True)
class TradeOrder:
    """One market entry intent before persistence in the trade ledger.

    ``target_quantity`` is the full intended position size (whole shares or
    fractional crypto size). The ledger row is completed when the broker
    reports that the market order is fully filled.

    ``idea_id`` is optional: set only when the order executes a row in the
    trade-ideas table. Strategies that trade without ideas leave it ``None``.
    """

    strategy: str
    symbol: str
    side: str
    target_quantity: float
    submitted_at: datetime
    idea_id: str | None = None

    def __post_init__(self) -> None:
        """Reject malformed orders at the domain boundary."""
        if not self.strategy.strip():
            raise ValueError("strategy must not be empty")

        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be a nonempty normalized symbol")

        if not self.side.strip():
            raise ValueError("side must not be empty")

        if not isfinite(self.target_quantity) or self.target_quantity <= 0:
            raise ValueError("target_quantity must be positive")

        if not isinstance(self.submitted_at, datetime):
            raise ValueError("submitted_at must be a datetime")

        if self.idea_id is not None and not self.idea_id.strip():
            raise ValueError("idea_id must not be empty when provided")
