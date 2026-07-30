"""Strategy-owned open positions for multi-strategy portfolio accounting.

Alpaca sees one blended account; this domain is the per-strategy book of
record. Fill-driven fields own quantity and cost. Broker marks (unrealized
P&L, last price) are observational and arrive via a separate mark sync.
"""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Literal

PositionSide = Literal["long", "short"]

POSITION_SIDES: tuple[PositionSide, ...] = ("long", "short")


@dataclass(frozen=True, slots=True)
class Position:
    """One open position owned by a single strategy.

    Keys in storage are ``(strategy, symbol)``. ``quantity`` is always the
    open size after the latest fill (whole shares or fractional crypto);
    flat positions are deleted from the table rather than stored at zero.
    ``avg_cost`` comes from our fills, not the broker. ``idea_id`` links to
    the opening trade idea when one exists.
    """

    strategy: str
    symbol: str
    side: PositionSide
    quantity: float
    avg_cost: float
    opened_at: datetime
    updated_at: datetime
    idea_id: str | None = None

    def __post_init__(self) -> None:
        """Reject malformed positions at the domain boundary."""
        if not self.strategy.strip():
            raise ValueError("strategy must not be empty")

        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be a nonempty normalized symbol")

        if self.side not in POSITION_SIDES:
            raise ValueError(f"unknown side {self.side!r}; expected one of {POSITION_SIDES}")

        if not isfinite(self.quantity) or self.quantity <= 0:
            raise ValueError("quantity must be positive")

        if not isfinite(self.avg_cost) or self.avg_cost <= 0:
            raise ValueError("avg_cost must be positive")

        if not isinstance(self.opened_at, datetime):
            raise ValueError("opened_at must be a datetime")

        if not isinstance(self.updated_at, datetime):
            raise ValueError("updated_at must be a datetime")

        if self.updated_at < self.opened_at:
            raise ValueError("updated_at must not precede opened_at")

        if self.idea_id is not None and not self.idea_id.strip():
            raise ValueError("idea_id must not be empty when provided")


@dataclass(frozen=True, slots=True)
class PositionMarks:
    """Alpaca mark snapshot for one strategy-owned open position.

    Observational only — never used for sizing or order logic. Written by the
    mark sync onto an existing portfolio row keyed by ``(strategy, symbol)``.
    """

    strategy: str
    symbol: str
    unrealized_pl: float
    unrealized_plpc: float
    current_price: float
    market_value: float
    mark_synced_at: datetime

    def __post_init__(self) -> None:
        """Reject malformed mark snapshots at the domain boundary."""
        if not self.strategy.strip():
            raise ValueError("strategy must not be empty")

        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be a nonempty normalized symbol")

        if not isfinite(self.unrealized_pl):
            raise ValueError("unrealized_pl must be finite")

        if not isfinite(self.unrealized_plpc):
            raise ValueError("unrealized_plpc must be finite")

        if not isfinite(self.current_price) or self.current_price <= 0:
            raise ValueError("current_price must be positive")

        if not isfinite(self.market_value):
            raise ValueError("market_value must be finite")

        if not isinstance(self.mark_synced_at, datetime):
            raise ValueError("mark_synced_at must be a datetime")
