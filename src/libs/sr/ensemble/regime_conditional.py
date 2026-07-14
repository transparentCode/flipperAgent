"""
S/R v2 Ensemble — Regime Conditional Strategy
===============================================
Augments ``WeightedAverageEnsemble`` with regime-specific weight
adjustments.  Falls back to plain weighted_average when regime
is unavailable (via ``RegimeGate``).

See §2C and §2G of the architecture plan.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.sr.ensemble.base import BaseEnsembleStrategy
from app.sr.ensemble.registry import register_ensemble
from app.sr.ensemble.weighted_average import WeightedAverageEnsemble
from app.sr.models import CandidateLevel, LevelFeatureVector, ScoredLevel


@register_ensemble("regime_conditional")
class RegimeConditionalEnsemble(BaseEnsembleStrategy):
    """
    Regime-conditional ensemble scoring.

    Uses ``weighted_average`` as the base, then applies regime-specific
    weight multipliers from config:

    - ``regime_state == "trending"``  → ``weights.trending``
    - ``regime_state == "ranging"``   → ``weights.ranging``
    - ``regime_state == "volatile"``  → ``weights.volatile``

    When ``regime_state`` is ``None`` (regime unavailable or gated),
    falls back to plain weighted_average with uniform multiplier (1.0).
    """

    _base_ensemble = WeightedAverageEnsemble()

    @property
    def strategy_name(self) -> str:
        return "regime_conditional"

    def score(
        self,
        candidates: List[CandidateLevel],
        features: Dict[str, LevelFeatureVector],
        config: Dict[str, Any],
    ) -> List[ScoredLevel]:
        if not candidates:
            return []

        # Get base scored levels from weighted_average
        base_results = self._base_ensemble.score(candidates, features, config)

        # Determine regime state and multiplier
        regime_state: Optional[str] = config.get("regime_state")
        regime_weights: Dict[str, float] = config.get("regime_weights", {})
        fallback_weights: Dict[str, float] = config.get("fallback_weights", {
            "trending": 1.0, "ranging": 1.0, "volatile": 1.0,
        })

        if regime_state is None:
            # No regime → return base results as-is (uniform multiplier)
            return [
                ScoredLevel(
                    candidate=sl.candidate,
                    features=sl.features,
                    strength=sl.strength,
                    confidence=sl.confidence,
                    contributing_kernels=sl.contributing_kernels,
                    ensemble_method="weighted_average",  # Fell back
                    zone_quality=sl.zone_quality,
                    confluence_tier=sl.confluence_tier,
                )
                for sl in base_results
            ]

        # Apply regime multiplier
        multiplier = regime_weights.get(
            regime_state,
            fallback_weights.get(regime_state, 1.0),
        )

        adjusted: List[ScoredLevel] = []
        for sl in base_results:
            # Adjust strength by regime multiplier
            new_strength = min(1.0, sl.strength * multiplier)
            # Recompute ZQS with adjusted strength
            new_zq = self.compute_zone_quality(
                new_strength, sl.confidence, sl.candidate, sl.features, config,
            )

            adjusted.append(ScoredLevel(
                candidate=sl.candidate,
                features=sl.features,
                strength=new_strength,
                confidence=sl.confidence,
                contributing_kernels=sl.contributing_kernels,
                ensemble_method=self.strategy_name,
                zone_quality=new_zq,
                confluence_tier=sl.confluence_tier,
            ))

        return adjusted
