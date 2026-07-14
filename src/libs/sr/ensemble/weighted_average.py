"""
S/R v2 Ensemble — Weighted Average Strategy
=============================================
Default ensemble: fixed weights per kernel, split into structural
vs microstructure groups controlled by ``structural_vs_micro_ratio``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set

from app.sr.ensemble.base import BaseEnsembleStrategy
from app.sr.ensemble.registry import register_ensemble
from app.sr.models import CandidateLevel, LevelFeatureVector, ScoredLevel


def _classify_kernel(name: str, structural_set: Set[str]) -> str:
    """Return 'structural' or 'micro' for a kernel name."""
    if name in structural_set:
        return "structural"
    return "micro"


@register_ensemble("weighted_average")
class WeightedAverageEnsemble(BaseEnsembleStrategy):
    """
    Weighted average scoring.

    Kernels are divided into structural (pivot, fractal, regression) and
    microstructure (VP, OB, FVG, round_number) groups.
    ``structural_vs_micro_ratio`` controls relative importance.
    Within-group weights are equal (or from ``kernel_weights`` if set).
    """

    @property
    def strategy_name(self) -> str:
        return "weighted_average"

    def score(
        self,
        candidates: List[CandidateLevel],
        features: Dict[str, LevelFeatureVector],
        config: Dict[str, Any],
    ) -> List[ScoredLevel]:
        if not candidates:
            return []

        ratio = config.get("structural_vs_micro_ratio", 0.5)
        kernel_weights: Dict[str, float] = config.get("kernel_weights", {})

        # Read kernel group classification from config (not hardcoded)
        structural_set: Set[str] = set(config.get(
            "structural_kernels",
            ["pivot_hl", "fractal_channel", "regression_band"],
        ))

        # Collect unique kernels in each group
        structural_names = {c.kernel_name for c in candidates
                           if _classify_kernel(c.kernel_name, structural_set) == "structural"}
        micro_names = {c.kernel_name for c in candidates
                       if _classify_kernel(c.kernel_name, structural_set) == "micro"}

        # Compute per-kernel weights
        weights = self._compute_weights(
            structural_names, micro_names, ratio, kernel_weights,
        )

        results: List[ScoredLevel] = []
        contributing_proximity = float(config.get("contributing_proximity_atr", 0.5))
        for c in candidates:
            key = self.candidate_key(c)
            fv = features.get(key, LevelFeatureVector())

            w = weights.get(c.kernel_name, 1.0)
            strength = min(1.0, c.raw_score * w)

            # Confidence from standardized feature computation
            confidence = self.compute_standardized_confidence(c, fv, config, config.get("regime_state"))

            # Contributing kernels: find others at same price zone
            contributing = self._find_contributing_kernels(
                c, candidates, contributing_proximity,
            )

            # Zone quality score (composite ZQS)
            zone_quality = self.compute_zone_quality(strength, confidence, c, fv, config)

            # Confluence tier (S/A/B/C)
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

    # ------------------------------------------------------------------

    @staticmethod
    def _compute_weights(
        structural: Set[str],
        micro: Set[str],
        ratio: float,
        explicit: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Compute per-kernel weight.

        When ``explicit`` kernel_weights are provided, use them as
        absolute multipliers (no budget-splitting).
        Otherwise, split total weight budget by ``ratio``: structural
        group gets ``ratio`` total, micro gets ``1 - ratio`` total,
        each divided evenly within the group.
        """
        weights: Dict[str, float] = {}
        all_kernels = structural | micro

        if explicit:
            # Absolute weights — no budget-splitting
            for name in all_kernels:
                weights[name] = explicit.get(name, 1.0)
        elif structural and micro:
            # Budget-based: total structural weight = ratio, total micro = 1 - ratio
            for name in structural:
                weights[name] = ratio / len(structural)
            for name in micro:
                weights[name] = (1.0 - ratio) / len(micro)
        else:
            # Single group only — equal share
            for name in all_kernels:
                weights[name] = 1.0 / max(1, len(all_kernels))

        return weights



    @staticmethod
    def _find_contributing_kernels(
        target: CandidateLevel,
        all_candidates: List[CandidateLevel],
        proximity_atr: float = 0.5,
    ) -> List[str]:
        """Find kernels that agree on this level (within proximity_atr ATR)."""
        atr = target.atr_at_detection
        if atr <= 0:
            return [target.kernel_name]

        contributing = set()
        for c in all_candidates:
            dist = abs(c.center_price - target.center_price) / atr
            if dist <= proximity_atr:
                contributing.add(c.kernel_name)

        return sorted(contributing)
