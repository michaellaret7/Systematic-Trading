"""Small validation helpers for screener panel contracts."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import pandas as pd


def require_columns(frame: pd.DataFrame, columns: Iterable[str], context: str) -> None:
    """Raise a clear error if ``frame`` lacks required columns."""
    required = list(columns)
    missing = [column for column in required if column not in frame.columns]

    if missing:
        raise ValueError(f"{context} is missing required columns: {missing}")


def require_unique_keys(frame: pd.DataFrame, keys: Sequence[str], context: str) -> None:
    """Raise when key duplicates would make downstream joins ambiguous."""
    require_columns(frame, keys, context)

    duplicated = frame.duplicated(list(keys), keep=False)
    if not duplicated.any():
        return

    examples = frame.loc[duplicated, list(keys)].drop_duplicates().head(5).to_dict("records")
    raise ValueError(f"{context} has duplicate key rows for {list(keys)}: {examples}")
