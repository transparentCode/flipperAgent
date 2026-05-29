"""Simple-weighted ensemble strategy.

Ported from v1 ``app/regression/ensemble/simple_weighted.py``.
Weights from config × per-method confidence.
v2 additions: agreement_score, degradation, dominant_method, method_weights.
"""
from __future__ import annotations

from collections import Counter
from typing import ClassVar, Dict, List, Optional

import numpy as np

from ..config.schema import PluginConfig
from ..contracts.context import CascadeContext, PipelineRequest
from ..contracts.result import DegradationLevel, EnsembleResult, MethodResult
from .base import EnsembleStrategy, EnsembleRegistry


@EnsembleRegistry.register("simple_weighted")
class SimpleWeightedEnsemble(EnsembleStrategy):
    requires: ClassVar[List[str]] = ["method_results"]
    provides: ClassVar[List[str]] = ["center", "slope", "direction", "confidence", "upper", "lower", "agreement_score"]

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._method_weights: Dict[str, float] = config.get("method_weights", {})
        self._neutral_slope_atr_fraction: float = config.get("neutral_slope_atr_fraction", 0.04)
        self.cascade_penalty: float = config.get("cascade_penalty", 0.5)
        self.cascade_boost_multiplier: float = config.get("cascade_boost_multiplier", 0.5)

    def combine(
        self,
        results: Dict[str, MethodResult],
        request: PipelineRequest,
        cascade: Optional[CascadeContext] = None,
    ) -> EnsembleResult:
        all_results = list(results.values())

        valid_results = [
            r for r in all_results
            if r.is_valid
            and r.center is not None
            and r.slope is not None
            and not np.isnan(r.slope)
        ]

        if not valid_results:
            return EnsembleResult(
                center=np.nan,
                slope=np.nan,
                direction="NEUTRAL",
                confidence=0.0,
                is_valid=False,
                degradation=DegradationLevel.FAILED,
                agreement_score=0.0,
                metadata={
                    "reason": "no_valid_method_results",
                    "total_submitted": len(all_results),
                },
            )

        # Band-type validation: only average bands from matching band_type
        band_types = [r.band_type for r in valid_results if r.upper is not None]
        dominant_band_type = Counter(band_types).most_common(1)[0][0] if band_types else None
        band_eligible = {
            r.method_name for r in valid_results
            if r.band_type == dominant_band_type
        }

        # Vectorized weight accumulation
        names = [r.method_name for r in valid_results]
        base_weights = np.array([self._method_weights.get(n, 1.0) for n in names])
        confidences = np.array([r.confidence for r in valid_results])
        centers = np.array([
            r.center[-1] if isinstance(r.center, np.ndarray) else r.center
            for r in valid_results
        ])
        slopes = np.array([r.slope for r in valid_results])
        intercepts = np.array([r.intercept for r in valid_results])

        effective_weights = base_weights * np.maximum(0.01, confidences)

        self._apply_cascade_adjustments(
            slopes=slopes,
            weights=effective_weights,
            cascade=cascade,
            cascade_penalty=self.cascade_penalty,
            cascade_boost_multiplier=self.cascade_boost_multiplier,
        )

        total_weight = float(np.sum(effective_weights))
        confidence_weight = float(np.sum(base_weights))

        if total_weight <= 0:
            return EnsembleResult(
                center=np.nan,
                slope=np.nan,
                direction="NEUTRAL",
                confidence=0.0,
                is_valid=False,
                degradation=DegradationLevel.FAILED,
                agreement_score=0.0,
                metadata={"reason": "zero_total_weight"},
            )

        weighted_center = float(np.dot(effective_weights, centers)) / total_weight
        weighted_slope = float(np.dot(effective_weights, slopes)) / total_weight
        weighted_intercept = float(np.dot(effective_weights, intercepts)) / total_weight
        weighted_confidence = float(np.dot(base_weights, confidences)) / confidence_weight if confidence_weight > 0 else 0.0

        # Band averaging — only from band_eligible methods
        upper_weight = 0.0
        lower_weight = 0.0
        weighted_upper = 0.0
        weighted_lower = 0.0

        for i, res in enumerate(valid_results):
            if res.method_name not in band_eligible:
                continue
            ew = effective_weights[i]
            if res.upper is not None:
                u = res.upper[-1] if isinstance(res.upper, np.ndarray) else res.upper
                if not np.isnan(u):
                    weighted_upper += u * ew
                    upper_weight += ew
            if res.lower is not None:
                lo = res.lower[-1] if isinstance(res.lower, np.ndarray) else res.lower
                if not np.isnan(lo):
                    weighted_lower += lo * ew
                    lower_weight += ew

        upper = (weighted_upper / upper_weight) if upper_weight > 0 else None
        lower = (weighted_lower / lower_weight) if lower_weight > 0 else None

        # Direction
        atr_norm = request.metadata.get("atr_norm", 0.0)
        neutral_threshold = atr_norm * self._neutral_slope_atr_fraction if atr_norm > 0 else 1e-6

        if weighted_slope > neutral_threshold:
            direction = "BULLISH"
        elif weighted_slope < -neutral_threshold:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        # Agreement score: 1 - (spread of slopes / max spread)
        if len(slopes) > 1:
            slope_spread = float(np.max(slopes) - np.min(slopes))
            mean_abs_slope = float(np.mean(np.abs(slopes)))
            agreement_score = 1.0 - min(1.0, slope_spread / max(mean_abs_slope, 1e-9))
            agreement_score = max(0.0, agreement_score)
        else:
            agreement_score = 1.0

        # Dominant method
        max_w_idx = int(np.argmax(effective_weights))
        dominant_method = names[max_w_idx]

        normalized_weights = {
            k: round(v / total_weight, 4)
            for k, v in zip(names, effective_weights.tolist())
        }

        degradation = (
            DegradationLevel.FULL
            if len(valid_results) == len(all_results)
            else DegradationLevel.PARTIAL
        )

        return EnsembleResult(
            center=float(weighted_center),
            slope=float(weighted_slope),
            intercept=float(weighted_intercept),
            direction=direction,
            upper=float(upper) if upper is not None else None,
            lower=float(lower) if lower is not None else None,
            confidence=float(weighted_confidence),
            is_valid=True,
            degradation=degradation,
            agreement_score=float(agreement_score),
            dominant_method=dominant_method,
            method_weights=normalized_weights,
            metadata={
                "total_weight": float(total_weight),
                "methods_submitted": len(all_results),
                "methods_valid": len(valid_results),
            },
        )
