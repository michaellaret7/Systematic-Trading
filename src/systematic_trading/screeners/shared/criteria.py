"""Criterion parsing and evaluation shared by screeners."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias, cast

import pandas as pd


Bound: TypeAlias = Literal["min", "max"]
CriteriaInput: TypeAlias = Mapping[str, float] | Sequence["Criterion"]


@dataclass(frozen=True, slots=True)
class Criterion:
    """One numeric gate applied to a metrics panel column."""

    column: str
    bound: Bound
    threshold: float

    @classmethod
    def from_legacy_key(cls, key: str, threshold: float) -> Criterion:
        """Build a criterion from the historical ``column_min`` / ``column_max`` form."""
        column, _, bound = key.rpartition("_")

        if not column or bound not in {"min", "max"}:
            raise ValueError(f"criterion {key!r} must end in '_min' or '_max'")

        return cls(column=column, bound=cast(Bound, bound), threshold=threshold)

    def evaluate(self, snapshot: pd.DataFrame) -> pd.Series:
        """Return True for rows satisfying this criterion."""
        if self.bound == "min":
            return snapshot[self.column] >= self.threshold

        return snapshot[self.column] <= self.threshold


def normalize_criteria(criteria: CriteriaInput) -> tuple[Criterion, ...]:
    """Accept both the legacy dict API and explicit ``Criterion`` objects."""
    if isinstance(criteria, Mapping):
        return tuple(
            Criterion.from_legacy_key(key, threshold) for key, threshold in criteria.items()
        )

    normalized = tuple(criteria)

    for criterion in normalized:
        if not isinstance(criterion, Criterion):
            raise TypeError("criteria must be a mapping or a sequence of Criterion objects")

    return normalized
