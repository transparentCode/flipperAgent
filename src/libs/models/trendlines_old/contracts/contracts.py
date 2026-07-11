"""Canonical contracts for trendline extraction and fitting.

These models are intentionally narrower than geometry's current boundary
contracts. They describe trendline inputs and outputs without pulling in
workflow, alpha, or orchestration concerns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np


@dataclass
class PivotSet:
    """Reduced structural highs and lows used for line fitting."""

    high_indices: np.ndarray
    high_values: np.ndarray
    low_indices: np.ndarray
    low_values: np.ndarray

    @property
    def n_highs(self) -> int:
        return len(self.high_indices)

    @property
    def n_lows(self) -> int:
        return len(self.low_indices)

    @property
    def total_pivots(self) -> int:
        return self.n_highs + self.n_lows

    def is_valid(self, min_pivots: int = 2) -> bool:
        return self.n_highs >= min_pivots and self.n_lows >= min_pivots


@dataclass
class Trendline:
    """A fitted support or resistance line in local index space."""

    start_index: int
    end_index: int
    start_value: float
    end_value: float
    slope: float
    intercept: float
    touch_count: int
    is_support: bool
    method: str = ""
    score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def value_at(self, index: float) -> float:
        return self.slope * index + self.intercept

    def project(self, steps_ahead: int) -> float:
        return self.value_at(self.end_index + steps_ahead)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_index": self.start_index,
            "end_index": self.end_index,
            "start_value": self.start_value,
            "end_value": self.end_value,
            "slope": self.slope,
            "intercept": self.intercept,
            "touch_count": self.touch_count,
            "is_support": self.is_support,
            "method": self.method,
            "score": self.score,
            "metadata": dict(self.metadata),
        }


@dataclass
class TrendlineFitResult:
    """Container for fitted support and resistance lines."""

    support_lines: List[Trendline] = field(default_factory=list)
    resistance_lines: List[Trendline] = field(default_factory=list)
    is_valid: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def best_support(self) -> Optional[Trendline]:
        if not self.support_lines:
            return None
        return max(self.support_lines, key=lambda line: line.score)

    @property
    def best_resistance(self) -> Optional[Trendline]:
        if not self.resistance_lines:
            return None
        return max(self.resistance_lines, key=lambda line: line.score)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "support_lines": [line.to_dict() for line in self.support_lines],
            "resistance_lines": [line.to_dict() for line in self.resistance_lines],
            "is_valid": self.is_valid,
            "metadata": dict(self.metadata),
        }


__all__ = ["PivotSet", "Trendline", "TrendlineFitResult"]
