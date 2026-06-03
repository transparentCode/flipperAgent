"""Unit tests for RegimeEnsembleBlender."""

from dataclasses import dataclass, field
from typing import Any, Dict

import pytest

from libs.contracts.signal import ScoringOutput
from libs.models.blender.ensemble import (
    REGIME_TO_GROUP,
    RegimeEnsembleBlender,
    _normalize_model_name,
)

# Ensemble groups list (mirrors rule_based.py)
ENSEMBLE_GROUPS = ["TREND_BULL", "TREND_BEAR", "RANGE", "CHOPPY", "TRANSITION"]


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
            "TREND_BULL": {
                "mean_reversion": 0.00,
                "momentum": 1.00,
                "squeeze_breakout": 0.00,
            },
            "TREND_BEAR": {
                "mean_reversion": 0.00,
                "momentum": 0.49,
                "squeeze_breakout": 0.51,
            },
            "RANGE": {
                "mean_reversion": 0.00,
                "momentum": 1.00,
                "squeeze_breakout": 0.00,
            },
            "CHOPPY": {
                "mean_reversion": 0.00,
                "momentum": 0.13,
                "squeeze_breakout": 0.87,
            },
            "TRANSITION": {
                "mean_reversion": 0.00,
                "momentum": 0.78,
                "squeeze_breakout": 0.22,
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
        assert len(ENSEMBLE_GROUPS) == 5
        assert "TRANSITION" in ENSEMBLE_GROUPS


class TestModelNameNormalization:
    def test_runtime_model_names_normalize_to_config_aliases(self):
        assert _normalize_model_name("MeanReversion") == "mean_reversion"
        assert _normalize_model_name("SqueezeBreakout") == "squeeze_breakout"
        assert _normalize_model_name("SqueezeBreakoutScorer") == "squeeze_breakout"
        assert _normalize_model_name("Momentum") == "momentum"


class TestTrendBullWeights:
    def test_trend_bull_applies_momentum_only_weights(self):
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 1.0, "momentum": 1.0, "squeeze_breakout": 1.0})
        regime = FakeRegimeFeatures(regime="CLEAN_TREND_BULL", changepoint_prob=0.1)

        result = blender.blend(outputs, regime)

        assert result is not None
        # TREND_BULL weights: MR=0.00, Mom=1.00, SB=0.00
        # decay = max(0.15, 1.0 - 0.1) = 0.9
        expected = (0.00 + 1.00 + 0.00) * 0.9
        assert abs(result.edge_score - expected) < 1e-9


class TestTrendBearWeights:
    def test_trend_bear_applies_mom_sb_split_weights(self):
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 1.0, "momentum": 1.0, "squeeze_breakout": 1.0})
        regime = FakeRegimeFeatures(regime="VOLATILE_TREND_BEAR", changepoint_prob=0.05)

        result = blender.blend(outputs, regime)

        assert result is not None
        # TREND_BEAR weights: MR=0.00, Mom=0.49, SB=0.51
        # decay = max(0.15, 1.0 - 0.05) = 0.95
        expected = (0.00 + 0.49 + 0.51) * 0.95
        assert abs(result.edge_score - expected) < 1e-9


class TestRangeWeights:
    def test_range_applies_momentum_only_weights(self):
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 2.0, "momentum": -0.5, "squeeze_breakout": 0.3})
        regime = FakeRegimeFeatures(regime="QUIET_MR_RANGE", changepoint_prob=0.0)

        result = blender.blend(outputs, regime)

        assert result is not None
        # RANGE weights: MR=0.00, Mom=1.00, SB=0.00
        # decay = max(0.15, 1.0) = 1.0
        expected = (0.00 * 2.0 + 1.00 * (-0.5) + 0.00 * 0.3) * 1.0
        assert abs(result.edge_score - expected) < 1e-9

    def test_squeeze_maps_to_range(self):
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 0.5, "momentum": 0.5, "squeeze_breakout": 2.0})
        regime = FakeRegimeFeatures(regime="QUIET_MR_SQUEEZE", changepoint_prob=0.0)

        result = blender.blend(outputs, regime)

        assert result is not None
        assert result.metadata["base_group"] == "RANGE"


class TestChoppyWeights:
    def test_choppy_applies_sb_dominant_weights(self):
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"mean_reversion": 1.0, "momentum": 1.0, "squeeze_breakout": 1.0})
        regime = FakeRegimeFeatures(regime="CHOPPY", changepoint_prob=0.0)

        result = blender.blend(outputs, regime)

        assert result is not None
        # CHOPPY weights: MR=0.00, Mom=0.13, SB=0.87
        expected = (0.00 + 0.13 + 0.87) * 1.0
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

    def test_runtime_meta_names_match_alias_weights(self):
        blender = RegimeEnsembleBlender(_default_config())
        outputs = _make_scoring_outputs({"MeanReversion": 0.5, "Momentum": 0.8, "SqueezeBreakout": 0.2})
        regime = FakeRegimeFeatures(regime="CLEAN_TREND_BULL", changepoint_prob=0.1)

        result = blender.blend(outputs, regime)

        assert result is not None
        assert abs(result.edge_score - (0.8 * 0.9)) < 1e-9
        assert result.metadata["weights_used"]["Momentum"] == 1.0
        assert result.metadata["weights_used"]["MeanReversion"] == 0.0


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
