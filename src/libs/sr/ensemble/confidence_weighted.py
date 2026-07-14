"""
S/R v2 Ensemble — Confidence Weighted Strategy
================================================
Weights kernel outputs by their own confidence / raw_score,
giving higher trust to kernels that report higher certainty.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set

from app.sr.ensemble.base import BaseEnsembleStrategy
from app.sr.ensemble.registry import register_ensemble
from app.sr.ensemble.weighted_average import WeightedAverageEnsemble
from app.sr.models import CandidateLevel, LevelFeatureVector, ScoredLevel


@register_ensemble("confidence_weighted")
class ConfidenceWeightedEnsemble(BaseEnsembleStrategy):
    """
    Confidence-weighted scoring.

    Each candidate's strength is its ``raw_score`` weighted by the
    kernel's average raw_score across all its candidates (self-calibration).
    Confidence is computed identically to ``WeightedAverageEnsemble``.
    """

    @property
    def strategy_name(self) -> str:
        return "confidence_weighted"

    def score(
        self,
        candidates: List[CandidateLevel],
        features: Dict[str, LevelFeatureVector],
        config: Dict[str, Any],
    ) -> List[ScoredLevel]:
        if not candidates:
            return []

        confidence_weighted_cfg = config.get("confidence_weighted", {})
        kernel_avg_baselines = confidence_weighted_cfg.get("kernel_avg_baselines", {})
        if not isinstance(kernel_avg_baselines, dict):
            kernel_avg_baselines = {}

        # Compute per-kernel average raw_score as calibration baseline
        kernel_sums: Dict[str, float] = {}
        kernel_counts: Dict[str, int] = {}
        for c in candidates:
            kernel_sums[c.kernel_name] = kernel_sums.get(c.kernel_name, 0.0) + c.raw_score
            kernel_counts[c.kernel_name] = kernel_counts.get(c.kernel_name, 0) + 1

        kernel_avg: Dict[str, float] = {
            k: kernel_sums[k] / kernel_counts[k]
            for k in kernel_sums
        }

        for kernel_name, baseline in kernel_avg_baselines.items():
            try:
                baseline_value = float(baseline)
            except (TypeError, ValueError):
                continue
            if baseline_value > 0:
                kernel_avg[str(kernel_name)] = baseline_value

        results: List[ScoredLevel] = []
        weight_cap = float(confidence_weighted_cfg.get("weight_cap", config.get("weight_cap", 2.0)))
        contributing_proximity = float(config.get("contributing_proximity_atr", 0.5))
        for c in candidates:
            key = self.candidate_key(c)
            fv = features.get(key, LevelFeatureVector())

            avg = kernel_avg.get(c.kernel_name, 0.5)
            # Weight by ratio of this candidate's score to kernel average
            weight = c.raw_score / avg if avg > 0 else 1.0
            strength = min(1.0, c.raw_score * min(weight, weight_cap))

            confidence = self.compute_standardized_confidence(c, fv, config, config.get("regime_state"))
            contributing = WeightedAverageEnsemble._find_contributing_kernels(
                c, candidates, contributing_proximity,
            )

            # Structural set for confluence tier
            structural_set: Set[str] = set(config.get(
                "structural_kernels",
                ["pivot_hl", "fractal_channel", "regression_band"],
            ))
            zone_quality = self.compute_zone_quality(strength, confidence, c, fv, config)
            confluence_tier = self.compute_confluence_tier(fv, contributing, structural_set)

            results.append(ScoredLevel(
                candidate=c,
                features=fv,
                strength=strength,
                confidence=confidence,
                contributing_kernels=contributing,
                ensemble_method=self.strategy_name,
                zone_quality=zone_quality,
                confluence_tier=confluence_tier,
            ))

        return results
