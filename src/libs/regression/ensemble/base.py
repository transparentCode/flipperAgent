from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Dict, List, Optional

import numpy as np

from ..config.schema import PluginConfig, ResolvedPipelineConfig
from ..contracts.context import CascadeContext, PipelineRequest
from ..contracts.result import EnsembleResult, MethodResult
from ..registry import PluginRegistry
from ..state import StateManager

EnsembleRegistry: PluginRegistry["EnsembleStrategy"] = PluginRegistry("ensemble")


class EnsembleStrategy(ABC):
    """Base class for ensemble blending strategies."""

    requires: ClassVar[List[str]] = ["method_results"]
    provides: ClassVar[List[str]] = ["center", "slope", "direction", "confidence", "upper", "lower", "agreement_score"]
    min_warmup_bars: ClassVar[int] = 0
    stateful: ClassVar[bool] = False

    def __init__(self, config: PluginConfig) -> None:
        self.config = config

    @abstractmethod
    def combine(
        self,
        results: Dict[str, MethodResult],
        request: PipelineRequest,
        cascade: Optional[CascadeContext] = None,
    ) -> EnsembleResult:
        """Blend multiple method results into a single ensemble result.

        Must populate:
            - agreement_score (float 0-1)
            - degradation level
            - dominant_method
            - method_weights
        """
        ...

    def _apply_cascade_adjustments(
        self,
        slopes: np.ndarray,
        weights: np.ndarray,
        cascade: Optional[CascadeContext],
        cascade_penalty: float,
        cascade_boost_multiplier: float = 0.5,
    ) -> None:
        """Apply in-place cascade penalty/boost to weights."""
        if cascade is None or cascade.direction == "NEUTRAL":
            return

        for i, slope in enumerate(slopes):
            if (slope > 0 and cascade.direction == "BEARISH") or (slope < 0 and cascade.direction == "BULLISH"):
                penalty = 1.0 - (cascade.confidence * cascade_penalty)
                weights[i] *= max(0.01, penalty)
            elif (slope > 0 and cascade.direction == "BULLISH") or (slope < 0 and cascade.direction == "BEARISH"):
                boost = 1.0 + (cascade.confidence * cascade_penalty * cascade_boost_multiplier)
                weights[i] *= boost

    def save_state(self, state_manager: StateManager, asset: str, timeframe: str) -> None:
        pass

    def load_state(self, state_manager: StateManager, asset: str, timeframe: str) -> None:
        pass

    def reset_state(self) -> None:
        pass
