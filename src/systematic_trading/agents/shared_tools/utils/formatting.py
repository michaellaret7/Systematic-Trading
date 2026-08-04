"""Shared text formatting for agent tools that return labelled number blocks.

An LLM reads a labelled snapshot far better than a wide grid of numbers, so the
price tools render aligned rows rather than raw tables.
"""

from typing import Any, Sequence

import pandas as pd

LABEL_WIDTH = 12
CELL_WIDTH = 10


def fmt(value: Any, decimals: int = 2) -> str:
    """Fixed-decimal string, or 'n/a' when the value is missing."""
    return f"{float(value):.{decimals}f}" if pd.notna(value) else "n/a"


def day(value: Any) -> str:
    """Render a date cell as YYYY-MM-DD."""
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def aligned_table(
    rows: Sequence[Sequence[str]],
    label_width: int = LABEL_WIDTH,
    cell_width: int = CELL_WIDTH,
) -> str:
    """Left-align each row's first cell and right-align the rest, one line per row."""
    lines = []

    for row in rows:
        label, *cells = row

        lines.append(
            f"  {label:<{label_width}}" + "".join(f"{cell:>{cell_width}}" for cell in cells)
        )

    return "\n".join(lines)
