"""Trendlines-native temporal signal extractor."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from libs.models.trendlines.boundary import BoundaryResult

from .base import AlphaSignal, BaseAlphaExtractor
from .utils import series_acceleration, count_persistent_rays

# ── Hardcoded constants (architecture constants, not asset-specific) ──
_CONVERGENCE_CONF_LO = 0.3
_CONVERGENCE_CONF_HI = 0.7
_PERSISTENCE_DIFF_THRESHOLD = 0.1
_PERSISTENCE_CONF_LO = 0.3
_PERSISTENCE_CONF_SPAN = 0.5
_SLOPE_ACCEL_BASE = 0.3
_SLOPE_ACCEL_MULT = 5.0


class TemporalAlphaExtractor(BaseAlphaExtractor):
    """Extract signals from the evolution of boundary results over time."""

    def __init__(
        self,
        *,
        min_history: int = 3,
        slope_match_tol: float = 0.05,
        convergence_rate_threshold: float = 0.2,
        slope_accel_threshold: float = 0.01,
        state_transitions: Dict[Tuple[str, str], Tuple[float, float]] | None = None,
        **params: Any,
    ):
        super().__init__(name="temporal", **params)
        self.min_history = min_history
        self.slope_match_tol = slope_match_tol
        self.convergence_rate_threshold = convergence_rate_threshold
        self.slope_accel_threshold = slope_accel_threshold
        self.state_transitions = state_transitions or {}

    def extract(
        self,
        result: BoundaryResult,
        history: Optional[List[BoundaryResult]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[AlphaSignal]:
        signals: List[AlphaSignal] = []
        if not result.is_valid:
            return signals
        if history is None or len(history) < self.min_history:
            return signals

        tf = result.timeframe

        sig = self._hull_convergence_signal(result, history, tf)
        if sig is not None:
            signals.append(sig)

        sig = self._state_transition_signal(result, history, tf)
        if sig is not None:
            signals.append(sig)

        sig = self._ray_persistence_signal(result, history, tf)
        if sig is not None:
            signals.append(sig)

        sig = self._slope_acceleration_signal(result, history, tf)
        if sig is not None:
            signals.append(sig)

        return signals

    def _hull_convergence_signal(
        self, result: BoundaryResult, history: List[BoundaryResult], tf: str
    ) -> Optional[AlphaSignal]:
        hull_widths: List[float] = []
        for br in history:
            if br.quality_metrics and br.quality_metrics.hull_width_atr > 0:
                hull_widths.append(br.quality_metrics.hull_width_atr)
        if result.quality_metrics and result.quality_metrics.hull_width_atr > 0:
            hull_widths.append(result.quality_metrics.hull_width_atr)

        if len(hull_widths) < self.min_history:
            return None

        recent = hull_widths[-self.min_history :]
        diffs = [recent[i + 1] - recent[i] for i in range(len(recent) - 1)]
        mean_diff = sum(diffs) / len(diffs) if diffs else 0.0

        if mean_diff >= 0:
            return None

        convergence_rate = abs(mean_diff) / max(recent[0], 1e-9)
        rt = self.convergence_rate_threshold
        confidence = min(1.0, _CONVERGENCE_CONF_LO + (_CONVERGENCE_CONF_HI - _CONVERGENCE_CONF_LO) * min(convergence_rate / rt, 1.0))

        return AlphaSignal(
            name="hull_convergence",
            direction=0.0,
            confidence=round(confidence, 4),
            source=self.name,
            timeframe=tf,
            metadata={
                "hull_widths": [round(w, 3) for w in recent],
                "mean_diff": round(mean_diff, 4),
                "convergence_rate": round(convergence_rate, 4),
            },
        )

    def _state_transition_signal(
        self, result: BoundaryResult, history: List[BoundaryResult], tf: str
    ) -> Optional[AlphaSignal]:
        prev = history[-1]
        prev_state = prev.interaction
        curr_state = result.interaction

        if prev_state == curr_state:
            return None

        key = (prev_state, curr_state)
        if key not in self.state_transitions:
            return None

        direction, confidence = self.state_transitions[key]

        return AlphaSignal(
            name=f"transition_{prev_state.lower()}_to_{curr_state.lower()}",
            direction=direction,
            confidence=round(confidence, 4),
            source=self.name,
            timeframe=tf,
            metadata={
                "from_state": prev_state,
                "to_state": curr_state,
            },
        )

    def _ray_persistence_signal(
        self, result: BoundaryResult, history: List[BoundaryResult], tf: str
    ) -> Optional[AlphaSignal]:
        persistence_bars = self.min_history + 2
        window = history[-persistence_bars:]

        s_persist = count_persistent_rays(
            result.active_support_rays,
            window,
            is_support=True,
            slope_match_tol=self.slope_match_tol,
        )
        r_persist = count_persistent_rays(
            result.active_resistance_rays,
            window,
            is_support=False,
            slope_match_tol=self.slope_match_tol,
        )

        total = len(result.active_support_rays) + len(result.active_resistance_rays)
        if total == 0:
            return None

        s_ratio = s_persist / max(len(result.active_support_rays), 1)
        r_ratio = r_persist / max(len(result.active_resistance_rays), 1)

        diff = s_ratio - r_ratio
        if abs(diff) < _PERSISTENCE_DIFF_THRESHOLD:
            return None

        direction = 1.0 if diff > 0 else -1.0
        confidence = min(1.0, _PERSISTENCE_CONF_LO + _PERSISTENCE_CONF_SPAN * abs(diff))

        return AlphaSignal(
            name="ray_persistence_bias",
            direction=direction,
            confidence=round(confidence, 4),
            source=self.name,
            timeframe=tf,
            metadata={
                "support_persistence": round(s_ratio, 3),
                "resistance_persistence": round(r_ratio, 3),
                "persistent_support_count": s_persist,
                "persistent_resistance_count": r_persist,
            },
        )

    def _slope_acceleration_signal(
        self, result: BoundaryResult, history: List[BoundaryResult], tf: str
    ) -> Optional[AlphaSignal]:
        s_slopes: List[float] = []
        r_slopes: List[float] = []

        for br in history:
            if br.best_support:
                s_slopes.append(br.best_support.slope)
            if br.best_resistance:
                r_slopes.append(br.best_resistance.slope)

        if len(s_slopes) < self.min_history and len(r_slopes) < self.min_history:
            return None

        s_accel = series_acceleration(s_slopes) if len(s_slopes) >= 2 else 0.0
        r_accel = series_acceleration(r_slopes) if len(r_slopes) >= 2 else 0.0

        combined = s_accel + r_accel
        if abs(combined) < self.slope_accel_threshold:
            return None

        direction = 1.0 if combined > 0 else -1.0
        confidence = min(1.0, _SLOPE_ACCEL_BASE + _SLOPE_ACCEL_MULT * abs(combined))

        return AlphaSignal(
            name="slope_acceleration",
            direction=direction,
            confidence=round(confidence, 4),
            source=self.name,
            timeframe=tf,
            metadata={
                "support_accel": round(s_accel, 6),
                "resistance_accel": round(r_accel, 6),
                "combined": round(combined, 6),
            },
        )


__all__ = ["TemporalAlphaExtractor"]