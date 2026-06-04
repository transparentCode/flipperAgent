"""Contracts for regime classification feature emission."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RegimeFeatureOutput:
    """Continuous regime descriptors emitted without trading decisions."""

    probabilities: dict[str, float]
    descriptors: dict[str, float]
    metadata: dict[str, Any] = field(default_factory=dict)

    def flatten(self, prefix: str = "regime") -> dict[str, float]:
        """Flatten probabilities and descriptors for DataFrame/model metadata use."""
        row: dict[str, float] = {}
        for name, value in self.probabilities.items():
            row[f"{prefix}_prob_{name}"] = float(value)
        for name, value in self.descriptors.items():
            row[f"{prefix}_{name}"] = float(value)
        return row
