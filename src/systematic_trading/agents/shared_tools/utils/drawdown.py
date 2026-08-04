"""Compact anatomy of a ticker's recent decline.

A drawdown decision turns on *how* a stock fell, not just how far: a handful of
gap-downs on heavy volume points at an event to go read about, while a slow
bleed on ordinary volume points at drift. The dates this returns are what a news
researcher needs to explain the move.
"""

from datetime import date

import pandas as pd

from systematic_trading.agents.shared_tools.utils.formatting import day, fmt
from systematic_trading.data.repository import load_daily_prices

# The actionable decline is the one from the trailing-year high; a name years
# into a structural slide would otherwise report a single multi-year episode.
RECENT_PEAK_BARS = 252

# A decline shallower than this is noise; no anatomy is worth printing.
ANATOMY_MIN_PCT = -5.0

# An open below the prior close by this much is treated as a gap.
GAP_DOWN_PCT = 3.0

# Trading days before the peak used as the volume baseline.
VOLUME_BASELINE_BARS = 60

# Only the deepest gaps are worth naming; the rest are a count.
MAX_GAPS_SHOWN = 3

# Share of the downside landing in three days before it reads as an event.
EVENT_CONCENTRATION_PCT = 60.0


def _drop_pct(close: pd.Series, start: int, end: int) -> float:
    """Percent change in close between two positions."""
    return (float(close.iloc[end]) / float(close.iloc[start]) - 1.0) * 100.0


def _anatomy(frame: pd.DataFrame, peak: int, trough: int) -> list[str]:
    """How the peak-to-trough decline happened: speed, concentration, gaps, volume."""
    decline = frame.iloc[peak : trough + 1]

    if len(decline) < 2:
        return ["  the decline happened in a single bar"]

    daily_pct = decline["close"].pct_change(fill_method=None).iloc[1:] * 100.0
    down_days = daily_pct[daily_pct < 0]

    worst = int(daily_pct.idxmin())
    baseline = float(frame["volume"].iloc[max(0, peak - VOLUME_BASELINE_BARS) : peak].mean())
    concentration = float(down_days.nsmallest(3).sum() / down_days.sum() * 100.0)

    prior_close = frame["close"].shift(1).iloc[peak + 1 : trough + 1]
    gaps = ((decline["open"].iloc[1:] / prior_close - 1.0) * 100.0).pipe(
        lambda pct: pct[pct <= -GAP_DOWN_PCT]
    )

    character = "EVENT" if concentration >= EVENT_CONCENTRATION_PCT else "BROAD DECLINE"

    lines = [
        f"  decline ran {trough - peak} bars, {len(down_days)} down days of {len(daily_pct)}",
        f"  worst day {fmt(daily_pct.min())}% on {day(frame['date'].iloc[worst])}"
        f" ({fmt(float(frame['volume'].iloc[worst]) / baseline)}x pre-peak volume)",
        f"  worst 3 days are {fmt(concentration)}% of all downside -> {character}",
    ]

    if len(gaps) > 0:
        named = ", ".join(
            f"{day(frame['date'].iloc[i])} {fmt(v)}%"
            for i, v in gaps.nsmallest(MAX_GAPS_SHOWN).items()
        )
        lines.append(f"  gap-downs over {fmt(GAP_DOWN_PCT)}%: {len(gaps)} (deepest {named})")

    return lines


def drawdown_block(symbol: str, start: date) -> str:
    """Where the stock sits against its trailing-year high, and how it got there."""
    frame = load_daily_prices(symbols=[symbol], start=start)

    if frame.empty:
        return "  no price history"

    frame = frame.sort_values("date").reset_index(drop=True)
    close = frame["close"]

    last = len(frame) - 1
    peak = int(close.iloc[max(0, len(frame) - RECENT_PEAK_BARS) :].idxmax())
    trough = int(close.iloc[peak:].idxmin())

    from_peak = _drop_pct(close, peak, last)

    lines = [
        f"  close {fmt(close.iloc[last])} | 252d peak {fmt(close.iloc[peak])}"
        f" on {day(frame['date'].iloc[peak])} ({fmt(from_peak)}%, {last - peak} bars ago)"
    ]

    if trough > peak:
        lines.append(
            f"  low since peak {fmt(close.iloc[trough])} on {day(frame['date'].iloc[trough])}"
            f" ({fmt(_drop_pct(close, peak, trough))}% from peak)"
            f" | bounce {fmt(_drop_pct(close, trough, last))}% over {last - trough} bars"
        )

    if _drop_pct(close, peak, trough) <= ANATOMY_MIN_PCT:
        lines.extend(_anatomy(frame, peak, trough))

    return "\n".join(lines)
