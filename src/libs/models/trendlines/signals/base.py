"""Canonical signal contracts for trendlines-native signal extraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.trendlines.boundary import BoundaryResult


@dataclass
class AlphaSignal:
    """A single directional signal derived from trendline structure."""

    name: str
    direction: float
    confidence: float
    source: str
    timeframe: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.direction = max(-1.0, min(1.0, self.direction))
        self.confidence = max(0.0, min(1.0, self.confidence))

    @property
    def is_long(self) -> bool:
        return self.direction > 0

    @property
    def is_short(self) -> bool:
        return self.direction < 0

    @property
    def strength(self) -> float:
        return abs(self.direction) * self.confidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "direction": round(self.direction, 4),
            "confidence": round(self.confidence, 4),
            "strength": round(self.strength, 4),
            "source": self.source,
            "timeframe": self.timeframe,
            "metadata": self.metadata,
        }


class BaseAlphaExtractor(ABC):
    """Abstract base class for trendlines-native signal extractors."""

    def __init__(self, name: str, **params: Any):
        self.name = name
        self.params = params

    @abstractmethod
    def extract(
        self,
        result: BoundaryResult,
        history: Optional[List[BoundaryResult]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[AlphaSignal]:
        """Extract zero or more structural signals from one boundary snapshot."""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, params={self.params})"


__all__ = ["AlphaSignal", "BaseAlphaExtractor"]