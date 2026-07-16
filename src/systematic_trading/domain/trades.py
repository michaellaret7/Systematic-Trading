"""Executed-trade records shared by strategies and the trade ledger."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite


@dataclass(frozen=True, slots=True)
class TradeFill:
    """One broker fill before persistence in the trade ledger."""

    strategy: str
    symbol: str
    side: str
    quantity: float
    price: float
    filled_at: datetime

    def __post_init__(self) -> None:
        """Reject malformed fills at the domain boundary."""
        if not self.strategy.strip():
            raise ValueError("strategy must not be empty")

        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be a nonempty normalized symbol")

        if not self.side.strip():
            raise ValueError("side must not be empty")

        if not isfinite(self.quantity) or self.quantity <= 0:
            raise ValueError("quantity must be positive")

        if not isfinite(self.price) or self.price <= 0:
            raise ValueError("price must be positive")

        if not isinstance(self.filled_at, datetime):
            raise ValueError("filled_at must be a datetime")
