"""Draft portfolio for the CSF Champions strategy.

A working object, not broker state: the build_portfolio workflow seeds it from
qualified trade ideas, the portfolio-constructor agent reshapes it through its
bound tools, and the submission step reads the final holdings once
construction ends. Dropped holdings are retained with their reasons so their
source ideas can be marked rejected downstream.
"""

from dataclasses import dataclass, field

from systematic_trading.domain.ideas import IdeaSide

# The conviction cut: ideas at or above it seed the book automatically and are
# protected from agent drops; ideas below it go to the candidate bench.
MIN_SCORE = 7.0

# Allocation policy: the book targets ~60% of the account; additions that would
# push the total past the hard cap are rejected at the tool boundary.
ALLOCATION_TARGET_PCT = 60.0
ALLOCATION_CAP_PCT = 65.0


@dataclass(slots=True)
class Holding:
    """One draft position, carrying its source idea for lifecycle updates."""

    idea_id: str = field(repr=False)
    ticker: str
    sector: str
    industry: str
    side: IdeaSide
    score: float
    weight_pct: float
    thesis: str = field(repr=False)
    reference_price: float
    max_entry_price: float


class Portfolio:
    """Mutable draft book: seeded from ideas, shaped by the constructor agent."""

    def __init__(self) -> None:
        self.holdings: dict[str, Holding] = {}
        self.dropped: dict[str, tuple[Holding, str]] = {}

    @property
    def total_weight(self) -> float:
        """Total allocation percentage across current holdings.

        Computed from the holdings on every access so it can never go stale,
        whichever tool mutated the book last.
        """
        return sum(holding.weight_pct for holding in self.holdings.values())

    def add(self, holding: Holding) -> None:
        """Add one holding; rejects duplicates so the book stays one-per-ticker."""
        if holding.ticker in self.holdings:
            raise ValueError(f"{holding.ticker} is already in the portfolio")

        self.holdings[holding.ticker] = holding

    def set_weight(self, ticker: str, weight_pct: float) -> None:
        """Resize one holding; raises KeyError if the ticker is not held."""
        self.holdings[ticker].weight_pct = weight_pct

    def drop(self, ticker: str, reason: str) -> None:
        """Remove one holding, retaining it with the reason for the reject step."""
        holding = self.holdings.pop(ticker)

        self.dropped[ticker] = (holding, reason)

    def summary(self) -> str:
        """Readable snapshot of the draft book, heaviest weight first."""
        if not self.holdings and not self.dropped:
            return "portfolio is empty"

        lines = [f"{len(self.holdings)} holdings:"]

        for h in sorted(self.holdings.values(), key=lambda h: -h.weight_pct):
            lines.append(
                f"  {h.ticker:<6} {h.side:<5} score {h.score:>4.1f}  "
                f"weight {h.weight_pct:>5.2f}%  ref ${h.reference_price:,.2f}  "
                f"max entry ${h.max_entry_price:,.2f}  {h.sector} / {h.industry}"
            )

        lines.append(f"total weight: {self.total_weight:.2f}%")

        if self.dropped:
            lines.append(f"dropped this run ({len(self.dropped)}):")
            lines.extend(f"  {ticker}: {reason}" for ticker, (_, reason) in self.dropped.items())

        return "\n".join(lines)
