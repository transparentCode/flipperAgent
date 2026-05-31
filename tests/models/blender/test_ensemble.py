"""Unit tests for RegimeEnsembleBlender."""

from dataclasses import dataclass, field
from typing import Any, Dict

import pytest

from libs.contracts.signal import ScoringOutput
from libs.models.blender.ensemble import RegimeEnsembleBlender, REGIME_TO_GROUP

# Ensemble groups list (mirrors rule_based.py)
ENSEMBLE_GROUPS = ["CLEAN_TREND", "VOLATILE_TREND", "QUIET_RANGE", "SQUEEZE", "CHOPPY", "TRANSITION"]


# ── Helpers ───────────────────────────────────────────────────────────────────

@dataclass
class FakeRegimeFeatures:
    """Minimal stand-in for RegimeFeatures used in blender tests."""
    regime: str = "CHOPPY"
    p_trending: float = 0.2
    vol_percentile: float = 50.0
    changepoint_prob: float = 0.1


def _default_config() -> dict:
    return {
        "transition": {
            "entry_threshold": 0.70,
            "exit_threshold": 0.30,
            "floor": 0.15,
        },
        "mtf": {
            "confirming_scale": 1.2,
            "conflicting_scale": 0.5,
        },
        "weights": {
            "CLEAN_TREND": {
                "mean_reversion": 0.15,
                "momentum": 0.55,
                "squeeze_breakout": 0.30,
            },
            "VOLATILE_TREND": {
                "mean_reversion": 0.50,
                "momentum": 0.20,
                "squeeze_breakout": 0.30,
            },
            "QUIET_RANGE": {
                "mean_reversion": 0.60,
                "momentum": 0.10,
                "squeeze_breakout": 0.30,
            },
            "SQUEEZE": {
                "mean_reversion": 0.15,
                "momentum": 0.25,
                "squeeze_breakout": 0.60,
            },
            "CHOPPY": {
                "mean_reversion": 0.30,
                "momentum": 0.10,
                "squeeze_breakout": 0.60,
            },
            "TRANSITION": {
                "mean_reversion": 0.33,
                "momentum": 0.34,
                "squeeze_breakout": 0.33,
            },
        },
    }


def _make_scoring_outputs(scores: dict[str, float], asset="BTCUSDT", tf="1h", ts=1000.0) -> list[ScoringOutput]:
    return [
        ScoringOutput(
            model_name=name,
            asset=asset,
            timeframe=tf,
            timestamp=ts,
            edge_score=score,
            conviction=0.8,
        )
        for name, score in scores.items()
    ]


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestRegimeToGroupMapping:
    def test_all_nine_regimes_mapped(self):
        assert len(REGIME_TO_GROUP) == 9

    def test_ensemble_groups_count(self):
        assert len(ENSEMBLE_GROUPS) == 6
        assert "TRANSITION" in ENSEMBLE_GROUPS


class TestCleanTrendWeights:
    def test_clean_trend_applies_momentum_heavy_weights(self):
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 1.0, "momentum": 1.0, "squeeze_breakout": 1.0})
        regime = FakeRegimeFeatures(regime="CLEAN_TREND_BULL", changepoint_prob=0.1)

        result = blender.blend(outputs, regime)

        assert result is not None
        # CLEAN_TREND weights: MR=0.15, Mom=0.55, SB=0.30 → weighted sum = 1.0
        # decay = max(0.15, 1.0 - 0.1) = 0.9
        expected = (0.15 + 0.55 + 0.30) * 0.9
        assert abs(result.edge_score - expected) < 1e-9


class TestVolatileTrendWeights:
    def test_volatile_trend_applies_mr_heavy_weights(self):
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 1.0, "momentum": 1.0, "squeeze_breakout": 1.0})
        regime = FakeRegimeFeatures(regime="VOLATILE_TREND_BEAR", changepoint_prob=0.05)

        result = blender.blend(outputs, regime)

        assert result is not None
        # VOLATILE_TREND weights: MR=0.50, Mom=0.20, SB=0.30
        # decay = max(0.15, 1.0 - 0.05) = 0.95
        expected = (0.50 + 0.20 + 0.30) * 0.95
        assert abs(result.edge_score - expected) < 1e-9


class TestQuietRangeWeights:
    def test_quiet_range_applies_mr_dominant_weights(self):
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 2.0, "momentum": -0.5, "squeeze_breakout": 0.3})
        regime = FakeRegimeFeatures(regime="QUIET_MR_RANGE", changepoint_prob=0.0)

        result = blender.blend(outputs, regime)

        assert result is not None
        # QUIET_RANGE weights: MR=0.60, Mom=0.10, SB=0.30
        # decay = max(0.15, 1.0) = 1.0
        expected = (0.60 * 2.0 + 0.10 * (-0.5) + 0.30 * 0.3) * 1.0
        assert abs(result.edge_score - expected) < 1e-9


class TestSqueezeWeights:
    def test_squeeze_applies_sb_dominant_weights(self):
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 0.5, "momentum": 0.5, "squeeze_breakout": 2.0})
        regime = FakeRegimeFeatures(regime="QUIET_MR_SQUEEZE", changepoint_prob=0.0)

        result = blender.blend(outputs, regime)

        assert result is not None
        # SQUEEZE weights: MR=0.15, Mom=0.25, SB=0.60
        expected = (0.15 * 0.5 + 0.25 * 0.5 + 0.60 * 2.0) * 1.0
        assert abs(result.edge_score - expected) < 1e-9


class TestChoppyWeights:
    def test_choppy_applies_sb_elevated_weights(self):
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 1.0, "momentum": 1.0, "squeeze_breakout": 1.0})
        regime = FakeRegimeFeatures(regime="CHOPPY", changepoint_prob=0.0)

        result = blender.blend(outputs, regime)

        assert result is not None
        # CHOPPY weights: MR=0.30, Mom=0.10, SB=0.60
        expected = (0.30 + 0.10 + 0.60) * 1.0
        assert abs(result.edge_score - expected) < 1e-9


class TestTransitionHysteresis:
    def test_transition_entry(self):
        """changepoint_prob > 0.70 triggers TRANSITION."""
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 1.0, "momentum": 1.0, "squeeze_breakout": 1.0})
        regime = FakeRegimeFeatures(regime="CLEAN_TREND_BULL", changepoint_prob=0.75)

        result = blender.blend(outputs, regime)

        assert result is not None
        assert result.metadata["regime_group"] == "TRANSITION"
        assert result.metadata["in_transition"] is True

    def test_transition_exit_requires_below_030(self):
        """Once in TRANSITION, must drop below 0.30 to exit."""
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 1.0, "momentum": 1.0, "squeeze_breakout": 1.0})

        # Enter transition
        blender.blend(outputs, FakeRegimeFeatures(regime="CHOPPY", changepoint_prob=0.80))
        assert blender._in_transition is True

        # Still in transition at 0.50 (between thresholds)
        result = blender.blend(outputs, FakeRegimeFeatures(regime="CHOPPY", changepoint_prob=0.50))
        assert result.metadata["regime_group"] == "TRANSITION"
        assert blender._in_transition is True

        # Exit transition at 0.25 (below exit threshold)
        result = blender.blend(outputs, FakeRegimeFeatures(regime="CHOPPY", changepoint_prob=0.25))
        assert result.metadata["regime_group"] == "CHOPPY"
        assert blender._in_transition is False


class TestTransitionDecayFloor:
    def test_decay_never_below_floor(self):
        """Even with changepoint_prob=1.0, decay is clamped at floor=0.15."""
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 1.0, "momentum": 1.0, "squeeze_breakout": 1.0})
        regime = FakeRegimeFeatures(regime="CHOPPY", changepoint_prob=1.0)

        result = blender.blend(outputs, regime)

        assert result is not None
        assert result.metadata["transition_decay"] == 0.15

    def test_decay_at_zero_changepoint(self):
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 1.0, "momentum": 1.0, "squeeze_breakout": 1.0})
        regime = FakeRegimeFeatures(regime="CHOPPY", changepoint_prob=0.0)

        result = blender.blend(outputs, regime)

        assert result.metadata["transition_decay"] == 1.0


class TestMTFScaling:
    def test_confirming_boost(self):
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 1.0, "momentum": 1.0, "squeeze_breakout": 1.0})
        regime = FakeRegimeFeatures(regime="CHOPPY", changepoint_prob=0.0)

        result_no_mtf = blender.blend(outputs, regime)
        result_confirming = blender.blend(outputs, regime, mtf_agreement="CONFIRMING")

        assert abs(result_confirming.edge_score - result_no_mtf.edge_score * 1.2) < 1e-9
        assert result_confirming.metadata["mtf_scale"] == 1.2

    def test_conflicting_penalty(self):
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 1.0, "momentum": 1.0, "squeeze_breakout": 1.0})
        regime = FakeRegimeFeatures(regime="CHOPPY", changepoint_prob=0.0)

        result_no_mtf = blender.blend(outputs, regime)
        result_conflicting = blender.blend(outputs, regime, mtf_agreement="CONFLICTING")

        assert abs(result_conflicting.edge_score - result_no_mtf.edge_score * 0.5) < 1e-9
        assert result_conflicting.metadata["mtf_scale"] == 0.5


class TestOutputCompatibility:
    def test_output_is_scoring_output(self):
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 0.5})
        regime = FakeRegimeFeatures(regime="CHOPPY", changepoint_prob=0.1)

        result = blender.blend(outputs, regime)

        assert isinstance(result, ScoringOutput)
        assert result.model_name == "regime_ensemble"
        assert result.asset == "BTCUSDT"
        assert result.timeframe == "1h"


class TestUnknownRegimeFallback:
    def test_unknown_regime_falls_back_to_choppy(self):
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 1.0, "momentum": 1.0, "squeeze_breakout": 1.0})
        regime = FakeRegimeFeatures(regime="UNKNOWN_REGIME_XYZ", changepoint_prob=0.1)

        result = blender.blend(outputs, regime)

        assert result is not None
        assert result.metadata["base_group"] == "CHOPPY"


class TestEmptyInputs:
    def test_empty_scoring_outputs_returns_none(self):
        blender = RegimeEnsembleBlender(_default_config())
        regime = FakeRegimeFeatures(regime="CHOPPY", changepoint_prob=0.1)

        result = blender.blend([], regime)

        assert result is None


class TestMetadataDebugInfo:
    def test_metadata_contains_debug_info(self):
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 0.5, "momentum": -0.3})
        regime = FakeRegimeFeatures(regime="QUIET_MR_RANGE", changepoint_prob=0.2)

        result = blender.blend(outputs, regime)

        assert result is not None
        meta = result.metadata
        assert "regime_group" in meta
        assert "base_group" in meta
        assert "transition_decay" in meta
        assert "mtf_scale" in meta
        assert "in_transition" in meta
        assert "weights_used" in meta
        assert "input_scores" in meta
        assert meta["input_scores"]["mean_reversion"] == 0.5
        assert meta["input_scores"]["momentum"] == -0.3
