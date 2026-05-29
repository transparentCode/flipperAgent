"""Confidence-weighted ensemble (MoE-style aggregation).

Ported from v1 ``app/regression/ensemble/confidence_weighted.py``.
Weights = base_trust × statistical_confidence, with max_method_weight cap.
min_confidence and max_method_weight extracted to config.
"""
from __future__ import annotations

import logging
from typing import ClassVar, Dict, List, Optional

import numpy as np

from ..config.schema import PluginConfig
from ..contracts.context import CascadeContext, PipelineRequest
from ..contracts.result import DegradationLevel, EnsembleResult, MethodResult
from .base import EnsembleStrategy, EnsembleRegistry

logger = logging.getLogger(__name__)


@EnsembleRegistry.register("confidence_weighted")
class ConfidenceWeightedEnsemble(EnsembleStrategy):
    requires: ClassVar[List[str]] = ["method_results"]
    provides: ClassVar[List[str]] = ["center", "slope", "direction", "confidence", "upper", "lower", "agreement_score"]

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self.base_weights: Dict[str, float] = config.get("base_weights", {})
        self.min_confidence: float = config.get("min_confidence", 0.05)
        self.max_method_weight: float = config.get("max_method_weight", 0.40)
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

        valid_models: List[str] = []
        raw_weights: List[float] = []
        slopes: List[float] = []
        intercepts: List[float] = []
        confidences: List[float] = []
        centers: List[float] = []
        uppers: List[float] = []
        lowers: List[float] = []

        for r in all_results:
            if not r.is_valid:
                continue
            if r.confidence < self.min_confidence:
                continue
            if np.isnan(r.slope) or np.isnan(r.intercept):
                continue

            base_w = self.base_weights.get(r.method_name, 1.0)
            voting_power = r.confidence * base_w

            valid_models.append(r.method_name)
            raw_weights.append(voting_power)
            slopes.append(r.slope)
            intercepts.append(r.intercept)
            confidences.append(r.confidence)
            centers.append(
                r.center[-1] if isinstance(r.center, np.ndarray) else r.center
            )
            if r.upper is not None:
                u = r.upper[-1] if isinstance(r.upper, np.ndarray) else r.upper
                uppers.append(u)
            else:
                uppers.append(None)
            if r.lower is not None:
                lo = r.lower[-1] if isinstance(r.lower, np.ndarray) else r.lower
                lowers.append(lo)
            else:
                lowers.append(None)

        if valid_models:
            np_raw_weights = np.array(raw_weights)
            self._apply_cascade_adjustments(
                slopes=np.array(slopes),
                weights=np_raw_weights,
                cascade=cascade,
                cascade_penalty=self.cascade_penalty,
                cascade_boost_multiplier=self.cascade_boost_multiplier,
            )
            raw_weights = np_raw_weights.tolist()

        if not valid_models:
            return EnsembleResult(
                center=np.nan,
                is_valid=False,
                degradation=DegradationLevel.FAILED,
                agreement_score=0.0,
                metadata={"reason": "no_valid_models_above_min_confidence"},
            )

        # Normalize weights
        total_weight = sum(raw_weights)
        if total_weight > 0:
            normalized = [w / total_weight for w in raw_weights]
        else:
            normalized = [1.0 / len(raw_weights)] * len(raw_weights)

        # Cap max_method_weight, redistribute excess
        if self.max_method_weight < 1.0 and len(normalized) > 1:
            for _ in range(5):
                excess = 0.0
                uncapped = []
                for i in range(len(normalized)):
                    if normalized[i] > self.max_method_weight:
                        excess += normalized[i] - self.max_method_weight
                        normalized[i] = self.max_method_weight
                    else:
                        uncapped.append(i)
                if excess <= 0:
                    break
                if not uncapped:
                    # Mathematical impossibility: all methods are at max cap but sum < 1.0.
                    # We must violate the cap to normalize to 1.0.
                    for i in range(len(normalized)):
                        normalized[i] += excess / len(normalized)
                    break
                uncapped_total = sum(normalized[i] for i in uncapped)
                if uncapped_total > 0:
                    for i in uncapped:
                        normalized[i] += excess * (normalized[i] / uncapped_total)

        np_nw = np.array(normalized)
        np_slopes = np.array(slopes)
        np_intercepts = np.array(intercepts)
        np_confidences = np.array(confidences)
        np_centers = np.array(centers)

        consensus_slope = float(np.dot(np_nw, np_slopes))
        consensus_intercept = float(np.dot(np_nw, np_intercepts))
        consensus_confidence = float(np.dot(np_nw, np_confidences))
        consensus_center = float(np.dot(np_nw, np_centers))

        upper_weight = 0.0
        weighted_upper = 0.0
        lower_weight = 0.0
        weighted_lower = 0.0
        for w, u, lo in zip(normalized, uppers, lowers):
            if u is not None and not np.isnan(u):
                weighted_upper += u * w
                upper_weight += w
            if lo is not None and not np.isnan(lo):
                weighted_lower += lo * w
                lower_weight += w

        consensus_upper = float(weighted_upper / upper_weight) if upper_weight > 0 else None
        consensus_lower = float(weighted_lower / lower_weight) if lower_weight > 0 else None

        # Direction
        atr_norm = request.metadata.get("atr_norm", 0.0)
        threshold = atr_norm * self._neutral_slope_atr_fraction if atr_norm > 0 else 1e-6

        if consensus_slope > threshold:
            direction = "BULLISH"
        elif consensus_slope < -threshold:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        # Dominant method
        max_w_idx = int(np.argmax(np_nw))
        dominant_method = valid_models[max_w_idx]

        weights_used = {name: round(float(w), 4) for name, w in zip(valid_models, normalized)}

        # Agreement score
        if len(np_slopes) > 1:
            slope_spread = float(np.max(np_slopes) - np.min(np_slopes))
            mean_abs = float(np.mean(np.abs(np_slopes)))
            agreement_score = max(0.0, 1.0 - min(1.0, slope_spread / max(mean_abs, 1e-9)))
        else:
            agreement_score = 1.0

        degradation = (
            DegradationLevel.FULL
            if len(valid_models) == len(all_results)
            else DegradationLevel.PARTIAL
        )

        return EnsembleResult(
            center=consensus_center,
            slope=consensus_slope,
            intercept=consensus_intercept,
            direction=direction,
            upper=consensus_upper,
            lower=consensus_lower,
            confidence=consensus_confidence,
            is_valid=True,
            degradation=degradation,
            agreement_score=agreement_score,
            dominant_method=dominant_method,
            method_weights=weights_used,
            metadata={
                "methods_submitted": len(all_results),
                "methods_valid": len(valid_models),
            },
        )
