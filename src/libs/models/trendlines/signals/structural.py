"""Trendlines-native structural signal extractor."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from libs.models.trendlines.boundary import BoundaryResult

from .base import AlphaSignal, BaseAlphaExtractor
from .constants import interaction_direction
from .quality import touch_count_confidence_factor

# ── Hardcoded constants (architecture constants, not asset-specific) ──
_BASE_INTERACTION_CONFIDENCE = 0.3
_SCORE_BLEND_WEIGHT = 0.6
_STRUCTURAL_INTERACTION_MULTIPLIER = 1.15
_SQUEEZE_CONFIDENCE_LO = 0.3
_SQUEEZE_CONFIDENCE_HI = 0.7
_SCORE_DIFF_THRESHOLD = 0.1
_SQUEEZE_DIRECTION_NUDGE = 0.3


class StructuralAlphaExtractor(BaseAlphaExtractor):
    """Extract signals from static structure at the current bar."""

    def __init__(
        self,
        *,
        asymmetry_threshold: float = 0.3,
        squeeze_threshold: float = 3.0,
        full_confidence_touches: float = 5.0,
        **params: Any,
    ):
        super().__init__(name="structural", **params)
        self.asymmetry_threshold = asymmetry_threshold
        self.squeeze_threshold = squeeze_threshold
        self.full_confidence_touches = full_confidence_touches

    def extract(
        self,
        result: BoundaryResult,
        history: Optional[List[BoundaryResult]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[AlphaSignal]:
        signals: List[AlphaSignal] = []
        if not result.is_valid:
            return signals

        tf = result.timeframe

        sig = self._interaction_signal(result, tf)
        if sig is not None:
            signals.append(sig)

        sig = self._squeeze_signal(result, tf)
        if sig is not None:
            signals.append(sig)

        sig = self._asymmetry_signal(result, tf)
        if sig is not None:
            signals.append(sig)

        return signals

    def _interaction_signal(self, result: BoundaryResult, tf: str) -> Optional[AlphaSignal]:
        interaction = result.interaction

        direction = interaction_direction(interaction)
        if direction == 0.0:
            return None

        best = result.best_support if direction > 0 else result.best_resistance
        if best is None:
            confidence = _BASE_INTERACTION_CONFIDENCE
        else:
            touch_factor = touch_count_confidence_factor(best.touch_count, self.full_confidence_touches)
            score_factor = best.score
            confidence = _BASE_INTERACTION_CONFIDENCE + (1.0 - _BASE_INTERACTION_CONFIDENCE) * (
                _SCORE_BLEND_WEIGHT * score_factor + (1.0 - _SCORE_BLEND_WEIGHT) * touch_factor
            )

        if "STRUCTURAL" in interaction:
            confidence = min(1.0, confidence * _STRUCTURAL_INTERACTION_MULTIPLIER)

        return AlphaSignal(
            name=f"interaction_{interaction.lower()}",
            direction=direction,
            confidence=round(confidence, 4),
            source=self.name,
            timeframe=tf,
            metadata={
                "interaction": interaction,
                "best_score": best.score if best else None,
                "best_touches": best.touch_count if best else None,
            },
        )

    def _squeeze_signal(self, result: BoundaryResult, tf: str) -> Optional[AlphaSignal]:
        qm = result.quality_metrics
        if qm is None or qm.hull_width_atr <= 0:
            return None

        hull_w = qm.hull_width_atr
        if hull_w >= self.squeeze_threshold:
            return None

        squeeze_ratio = 1.0 - (hull_w / self.squeeze_threshold)
        confidence = _SQUEEZE_CONFIDENCE_LO + (_SQUEEZE_CONFIDENCE_HI - _SQUEEZE_CONFIDENCE_LO) * squeeze_ratio

        direction = 0.0
        if result.best_support and result.best_resistance:
            s_score = result.best_support.score
            r_score = result.best_resistance.score
            if abs(s_score - r_score) > _SCORE_DIFF_THRESHOLD:
                direction = _SQUEEZE_DIRECTION_NUDGE if s_score > r_score else -_SQUEEZE_DIRECTION_NUDGE

        return AlphaSignal(
            name="hull_squeeze",
            direction=direction,
            confidence=round(confidence, 4),
            source=self.name,
            timeframe=tf,
            metadata={
                "hull_width_atr": round(hull_w, 4),
                "squeeze_ratio": round(squeeze_ratio, 4),
            },
        )

    def _asymmetry_signal(self, result: BoundaryResult, tf: str) -> Optional[AlphaSignal]:
        n_s = len(result.active_support_rays)
        n_r = len(result.active_resistance_rays)
        total = n_s + n_r

        if total < 2:
            return None

        s_score = result.best_support.score if result.best_support else 0.0
        r_score = result.best_resistance.score if result.best_resistance else 0.0

        count_asym = (n_s - n_r) / max(total, 1)
        score_asym = s_score - r_score
        combined = 0.5 * count_asym + 0.5 * score_asym

        if abs(combined) < self.asymmetry_threshold:
            return None

        direction = 1.0 if combined > 0 else -1.0
        confidence = min(1.0, abs(combined))

        return AlphaSignal(
            name="sr_asymmetry",
            direction=direction,
            confidence=round(confidence, 4),
            source=self.name,
            timeframe=tf,
            metadata={
                "n_support": n_s,
                "n_resistance": n_r,
                "s_score": round(s_score, 4),
                "r_score": round(r_score, 4),
                "combined_asymmetry": round(combined, 4),
            },
        )


__all__ = ["StructuralAlphaExtractor"]