"""Trendlines-native pattern signal extractor."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from libs.models.trendlines.boundary import BoundaryResult

from .base import AlphaSignal, BaseAlphaExtractor
from .quality import touch_count_confidence_factor

# ── Hardcoded constants (architecture constants, not asset-specific) ──
_QUALITY_WEIGHT = 0.5
_BLEND_BASE = 0.5
_BLEND_QUALITY = 0.3
_BLEND_TOUCH = 0.2


class PatternAlphaExtractor(BaseAlphaExtractor):
    """Detect chart patterns from ray slope geometry."""

    def __init__(
        self,
        *,
        parallel_tol: float = 0.02,
        flat_tol: float = 0.01,
        full_confidence_touches: float = 8.0,
        **params: Any,
    ):
        super().__init__(name="pattern", **params)
        self.parallel_tol = parallel_tol
        self.flat_tol = flat_tol
        self.full_confidence_touches = full_confidence_touches
        self.converging_min = self.parallel_tol * 1.5

    def extract(
        self,
        result: BoundaryResult,
        history: Optional[List[BoundaryResult]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[AlphaSignal]:
        signals: List[AlphaSignal] = []
        if not result.is_valid:
            return signals

        best_s = result.best_support
        best_r = result.best_resistance
        if best_s is None or best_r is None:
            return signals

        tf = result.timeframe
        s_slope = best_s.slope
        r_slope = best_r.slope

        pattern, direction, base_conf = self._classify_pattern(s_slope, r_slope)
        if pattern is None:
            return signals

        quality_factor = _QUALITY_WEIGHT * (best_s.score + best_r.score)
        total_touches = best_s.touch_count + best_r.touch_count
        touch_factor = touch_count_confidence_factor(
            total_touches,
            self.full_confidence_touches,
        )

        confidence = base_conf * (_BLEND_BASE + _BLEND_QUALITY * quality_factor + _BLEND_TOUCH * touch_factor)

        signals.append(
            AlphaSignal(
                name=f"pattern_{pattern}",
                direction=direction,
                confidence=round(min(1.0, confidence), 4),
                source=self.name,
                timeframe=tf,
                metadata={
                    "pattern": pattern,
                    "support_slope": round(s_slope, 6),
                    "resistance_slope": round(r_slope, 6),
                    "support_score": round(best_s.score, 4),
                    "resistance_score": round(best_r.score, 4),
                    "support_touches": best_s.touch_count,
                    "resistance_touches": best_r.touch_count,
                },
            )
        )

        return signals

    def _classify_pattern(self, s_slope: float, r_slope: float) -> Tuple[Optional[str], float, float]:
        slope_diff = abs(s_slope - r_slope)
        s_flat = abs(s_slope) <= self.flat_tol
        r_flat = abs(r_slope) <= self.flat_tol

        if slope_diff <= self.parallel_tol:
            if s_slope > self.flat_tol:
                return "ascending_channel", 1.0, 0.6
            if s_slope < -self.flat_tol:
                return "descending_channel", -1.0, 0.6
            return "horizontal_channel", 0.0, 0.5

        converging = s_slope > r_slope

        if converging and slope_diff >= self.converging_min:
            if r_flat and s_slope > self.flat_tol:
                return "ascending_triangle", 1.0, 0.75
            if s_flat and r_slope < -self.flat_tol:
                return "descending_triangle", -1.0, 0.75
            if s_slope > self.flat_tol and r_slope > self.flat_tol:
                return "rising_wedge", -0.7, 0.6
            if s_slope < -self.flat_tol and r_slope < -self.flat_tol:
                return "falling_wedge", 0.7, 0.6
            if not s_flat and not r_flat:
                mean_slope = (s_slope + r_slope) / 2.0
                direction = 0.3 if mean_slope > 0 else -0.3 if mean_slope < 0 else 0.0
                return "symmetric_triangle", direction, 0.65

        if not converging and slope_diff >= self.converging_min:
            return "broadening", 0.0, 0.45

        return None, 0.0, 0.0


__all__ = ["PatternAlphaExtractor"]