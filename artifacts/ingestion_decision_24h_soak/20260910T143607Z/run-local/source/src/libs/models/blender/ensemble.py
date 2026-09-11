"""RegimeEnsembleBlender — regime-conditioned model weight blender.

Sits between ScoringModelManager.evaluate() and SelectionLayer.select() inside
StrategyWorker.  Receives per-model ScoringOutput objects plus a RegimeFeatures
snapshot, then produces a single blended ScoringOutput.

Blending formula:
1. Determine regime group from 9-regime label via REGIME_TO_GROUP
2. Check TRANSITION override: if changepoint_prob > entry_threshold (0.70),
   enter transition state; exit when < exit_threshold (0.30)
3. Look up per-model weights for the active group
4. Compute blended score: sum(w_i * edge_score_i)
5. Apply transition decay: score *= max(floor, 1.0 - changepoint_prob)
6. Apply MTF scaling if mtf_agreement is available
"""

from __future__ import annotations

import logging
import re
from typing import Any

from libs.contracts.signal import ScoringOutput

logger = logging.getLogger(__name__)

# Regime → ensemble group mapping (mirrors REGIME_TO_GROUP in
# libs.regime.aggregation.rule_based — duplicated here to avoid triggering
# the broken app.regime import chain in libs.regime.__init__).
# Redesigned 2026-05-31: 9→4 grouping splits BULL/BEAR (opposite return profiles)
# instead of CLEAN/VOLATILE (no statistical difference). Research:
#   backtest_blender_redesign.ipynb — 12mo BTC+ETH 1h, 17474 bars.
REGIME_TO_GROUP: dict[str, str] = {
    "CLEAN_TREND_BULL":     "TREND_BULL",
    "CLEAN_TREND_BEAR":     "TREND_BEAR",
    "CLEAN_TREND_FLAT":     "RANGE",
    "VOLATILE_TREND_BULL":  "TREND_BULL",
    "VOLATILE_TREND_BEAR":  "TREND_BEAR",
    "VOLATILE_TREND_FLAT":  "CHOPPY",
    "QUIET_MR_RANGE":       "RANGE",
    "QUIET_MR_SQUEEZE":     "RANGE",
    "CHOPPY":               "CHOPPY",
}


def _normalize_model_name(name: str) -> str:
    """Normalize model identifiers to a config-friendly alias.

    Accepts runtime ``meta.name`` values like ``MeanReversion`` or
    ``SqueezeBreakoutScorer`` and converts them into the lowercase snake_case
    aliases used by blender config keys.
    """
    if not name:
        return ""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name)
    snake = re.sub(r"[^a-zA-Z0-9]+", "_", snake).strip("_").lower()
    for suffix in ("_scorer", "_model"):
        if snake.endswith(suffix):
            snake = snake[: -len(suffix)]
            break
    return snake


class RegimeEnsembleBlender:
    """Regime-conditioned model weight blender.

    Stateful: maintains ``_in_transition`` hysteresis flag across calls.
    Instantiated once per StrategyWorker lifetime.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        transition_cfg = config.get("transition", {})
        self.entry_threshold: float = transition_cfg.get("entry_threshold", 0.70)
        self.exit_threshold: float = transition_cfg.get("exit_threshold", 0.30)
        self.floor: float = transition_cfg.get("floor", 0.15)

        mtf_cfg = config.get("mtf", {})
        self.mtf_confirming_scale: float = mtf_cfg.get("confirming_scale", 1.2)
        self.mtf_conflicting_scale: float = mtf_cfg.get("conflicting_scale", 0.5)

        self.weights: dict[str, dict[str, float]] = config.get("weights", {})

        # Hysteresis state
        self._in_transition: bool = False

    @staticmethod
    def _lookup_weight(weights: dict[str, float], model_name: str) -> float:
        """Resolve blender weights against exact or normalized model names."""
        if model_name in weights:
            return weights[model_name]
        normalized_name = _normalize_model_name(model_name)
        if normalized_name in weights:
            return weights[normalized_name]
        for configured_name, weight in weights.items():
            if _normalize_model_name(configured_name) == normalized_name:
                return weight
        return 0.0

    def blend(
        self,
        scoring_outputs: list[ScoringOutput],
        regime_features: Any,
        mtf_agreement: str | None = None,
    ) -> ScoringOutput | None:
        """Blend multiple ScoringOutputs into a single regime-weighted output.

        Parameters
        ----------
        scoring_outputs:
            Per-model ScoringOutput objects from ScoringModelManager.evaluate().
        regime_features:
            RegimeFeatures dataclass with ``regime``, ``changepoint_prob``, etc.
        mtf_agreement:
            Optional multi-timeframe agreement: "CONFIRMING", "CONFLICTING", or None.

        Returns
        -------
        ScoringOutput with blended edge_score, or None if no inputs.
        """
        if not scoring_outputs:
            return None

        # 1. Determine group
        base_group = REGIME_TO_GROUP.get(regime_features.regime, "CHOPPY")

        # 2. Transition override (hysteresis)
        cp = regime_features.changepoint_prob
        if not self._in_transition and cp > self.entry_threshold:
            self._in_transition = True
        elif self._in_transition and cp < self.exit_threshold:
            self._in_transition = False

        active_group = "TRANSITION" if self._in_transition else base_group

        # 3. Look up weights
        weights = self.weights.get(active_group, {})

        # 4. Weighted sum
        blended_score = 0.0
        total_conviction = 0.0
        weights_used: dict[str, float] = {}
        for so in scoring_outputs:
            w = self._lookup_weight(weights, so.model_name)
            weights_used[so.model_name] = w
            blended_score += w * so.edge_score
            total_conviction += so.conviction

        mean_conviction = total_conviction / len(scoring_outputs)

        # 5. Transition decay with floor
        decay = max(self.floor, 1.0 - cp)
        blended_score *= decay

        # 6. MTF scaling
        mtf_scale = 1.0
        if mtf_agreement == "CONFIRMING":
            mtf_scale = self.mtf_confirming_scale
        elif mtf_agreement == "CONFLICTING":
            mtf_scale = self.mtf_conflicting_scale
        blended_score *= mtf_scale

        return ScoringOutput(
            model_name="regime_ensemble",
            asset=scoring_outputs[0].asset,
            timeframe=scoring_outputs[0].timeframe,
            timestamp=scoring_outputs[0].timestamp,
            edge_score=blended_score,
            conviction=mean_conviction,
            metadata={
                "regime_group": active_group,
                "base_group": base_group,
                "transition_decay": decay,
                "mtf_scale": mtf_scale,
                "in_transition": self._in_transition,
                "weights_used": weights_used,
                "input_scores": {so.model_name: so.edge_score for so in scoring_outputs},
            },
        )
