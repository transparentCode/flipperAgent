"""Tests for the SelectionLayer, strategies, and normalization."""

import json
from pathlib import Path

import pytest
import yaml

from libs.contracts.signal import (
    FeatureVector,
    ModelOutput,
    ScoringOutput,
    SelectionCandidate,
    SelectionResult,
)
from libs.selection.base import SelectionStrategy
from libs.selection.overlays import apply_regime_v2_trend_gate, preview_regime_v2_trend_gate
from libs.selection.regime_v2_shadow_log import persist_regime_v2_shadow_decision
from libs.selection.strategies import (
    ConvictionWeightedStrategy,
    OverlapPenalizedStrategy,
    TopKStrategy,
)
from libs.selection.selection_layer import SelectionLayer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def feature_vec():
    return FeatureVector(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1000.0,
        features={"RSI": 55.0, "MACD_line": 0.5},
        bar_data={"close": 100.0, "volume": 500.0},
    )


@pytest.fixture
def default_config():
    return {
        "strategy": "overlap_penalized_top_k",
        "top_k": 3,
        "min_edge_threshold": 0.0,
        "same_direction_penalty": 0.3,
        "max_penalty": 0.8,
    }


def _make_candidate(
    model_name: str = "test_model",
    asset: str = "BTCUSDT",
    timeframe: str = "1h",
    timestamp: float = 1000.0,
    direction: int = 1,
    edge_score: float = 0.8,
    conviction: float = 0.9,
    source_type: str = "threshold",
) -> SelectionCandidate:
    return SelectionCandidate(
        model_name=model_name,
        asset=asset,
        timeframe=timeframe,
        timestamp=timestamp,
        direction=direction,
        edge_score=edge_score,
        conviction=conviction,
        source_type=source_type,
    )


# ---------------------------------------------------------------------------
# Normalization Tests
# ---------------------------------------------------------------------------

class TestNormalization:
    """Test normalization of ModelOutput and ScoringOutput to SelectionCandidate."""

    def test_normalize_model_output_long(self):
        mo = ModelOutput(
            model_name="squeeze",
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000.0,
            direction=1,
            conviction=0.8,
        )
        candidate = SelectionLayer.normalize_model_output(mo)
        assert candidate.direction == 1
        assert candidate.edge_score == pytest.approx(0.8)
        assert candidate.conviction == 0.8
        assert candidate.source_type == "threshold"

    def test_normalize_model_output_short(self):
        mo = ModelOutput(
            model_name="mean_rev",
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000.0,
            direction=-1,
            conviction=0.6,
        )
        candidate = SelectionLayer.normalize_model_output(mo)
        assert candidate.direction == -1
        assert candidate.edge_score == pytest.approx(-0.6)
        assert candidate.source_type == "threshold"

    def test_normalize_scoring_output_positive(self):
        so = ScoringOutput(
            model_name="alpha_v1",
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000.0,
            edge_score=0.45,
            conviction=0.9,
        )
        candidate = SelectionLayer.normalize_scoring_output(so)
        assert candidate.direction == 1
        assert candidate.edge_score == pytest.approx(0.45)
        assert candidate.source_type == "scoring"

    def test_normalize_scoring_output_negative(self):
        so = ScoringOutput(
            model_name="alpha_v1",
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000.0,
            edge_score=-0.3,
            conviction=0.7,
        )
        candidate = SelectionLayer.normalize_scoring_output(so)
        assert candidate.direction == -1
        assert candidate.edge_score == pytest.approx(-0.3)

    def test_normalize_scoring_output_zero(self):
        so = ScoringOutput(
            model_name="alpha_v1",
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000.0,
            edge_score=0.0,
            conviction=0.5,
        )
        candidate = SelectionLayer.normalize_scoring_output(so)
        assert candidate.direction == 0
        assert candidate.edge_score == 0.0


# ---------------------------------------------------------------------------
# Strategy Tests
# ---------------------------------------------------------------------------

class TestConvictionWeightedStrategy:
    def test_ranks_correctly(self, feature_vec, default_config):
        candidates = [
            _make_candidate(model_name="low", edge_score=0.3, conviction=0.5),    # score=0.15
            _make_candidate(model_name="high", edge_score=0.9, conviction=0.9),   # score=0.81
            _make_candidate(model_name="mid", edge_score=0.6, conviction=0.7),    # score=0.42
        ]
        strategy = ConvictionWeightedStrategy()
        results = strategy.select(candidates, feature_vec, default_config)

        assert len(results) == 3
        assert results[0].candidate.model_name == "high"
        assert results[1].candidate.model_name == "mid"
        assert results[2].candidate.model_name == "low"
        assert results[0].rank == 1
        assert results[1].rank == 2
        assert results[2].rank == 3
        assert results[0].selection_score == pytest.approx(0.81)


class TestOverlapPenalizedStrategy:
    def test_penalizes_same_direction(self, feature_vec, default_config):
        # Two long candidates on same asset — second should be penalized
        candidates = [
            _make_candidate(model_name="A", direction=1, edge_score=0.8, conviction=0.9),   # base=0.72
            _make_candidate(model_name="B", direction=1, edge_score=0.7, conviction=0.8),   # base=0.56
        ]
        strategy = OverlapPenalizedStrategy()
        results = strategy.select(candidates, feature_vec, default_config)

        assert len(results) == 2
        # First one should have no penalties
        assert results[0].candidate.model_name == "A"
        assert results[0].penalties == {}

        # Second one should have overlap penalty
        assert results[1].candidate.model_name == "B"
        assert "overlap_penalty" in results[1].penalties
        assert results[1].selection_score < 0.56  # penalized below base

    def test_no_penalty_different_direction(self, feature_vec, default_config):
        candidates = [
            _make_candidate(model_name="A", direction=1, edge_score=0.8, conviction=0.9),
            _make_candidate(model_name="B", direction=-1, edge_score=0.7, conviction=0.8),
        ]
        strategy = OverlapPenalizedStrategy()
        results = strategy.select(candidates, feature_vec, default_config)

        # No penalties for different directions
        for r in results:
            assert r.penalties == {}

    def test_no_penalty_different_asset(self, feature_vec, default_config):
        candidates = [
            _make_candidate(model_name="A", asset="BTCUSDT", direction=1, edge_score=0.8, conviction=0.9),
            _make_candidate(model_name="B", asset="ETHUSDT", direction=1, edge_score=0.7, conviction=0.8),
        ]
        strategy = OverlapPenalizedStrategy()
        results = strategy.select(candidates, feature_vec, default_config)

        for r in results:
            assert r.penalties == {}


class TestTopKStrategy:
    def test_truncates_to_top_k(self, feature_vec, default_config):
        candidates = [
            _make_candidate(model_name=f"m{i}", edge_score=0.1 * (i + 1), conviction=0.8)
            for i in range(5)
        ]
        strategy = TopKStrategy()
        results = strategy.select(candidates, feature_vec, default_config)

        assert len(results) == 3  # top_k=3 from default_config

    def test_fewer_than_k(self, feature_vec, default_config):
        candidates = [
            _make_candidate(model_name="only_one", edge_score=0.5, conviction=0.8),
        ]
        strategy = TopKStrategy()
        results = strategy.select(candidates, feature_vec, default_config)

        assert len(results) == 1


# ---------------------------------------------------------------------------
# Optional Overlay Tests
# ---------------------------------------------------------------------------

class TestRegimeV2TrendGateOverlay:
    def test_disabled_gate_is_exact_noop(self, feature_vec):
        candidates = [
            _make_candidate(model_name="Momentum", direction=1),
            _make_candidate(model_name="OtherModel", direction=-1),
        ]
        result = apply_regime_v2_trend_gate(candidates, feature_vec, {"overlays": {"regime_v2_trend_gate": {"enabled": False}}})

        assert result is candidates

    def test_missing_regime_payload_is_noop(self, feature_vec):
        candidates = [_make_candidate(model_name="Momentum", direction=1)]
        result = apply_regime_v2_trend_gate(
            candidates,
            feature_vec,
            {"overlays": {"regime_v2_trend_gate": {"enabled": True}}},
        )

        assert result is candidates

    def test_enabled_gate_keeps_aligned_target_and_non_target(self):
        feature_vec = FeatureVector(
            asset="BTCUSDT",
            timeframe="4h",
            timestamp=1000.0,
            features={
                "regime_v2": {
                    "evidence": {"trend_direction": "bull", "confidence": 0.7},
                    "policy": {"allow_trend_following": True, "trend_score": 0.5},
                }
            },
            bar_data={"close": 100.0},
        )
        candidates = [
            _make_candidate(model_name="Momentum", direction=1),
            _make_candidate(model_name="TrendFollowing", direction=-1),
            _make_candidate(model_name="PriceAction", direction=-1),
        ]
        config = {
            "overlays": {
                "regime_v2_trend_gate": {
                    "enabled": True,
                    "mode": "gated",
                    "target_models": ["Momentum", "TrendFollowing"],
                    "min_trend_score": 0.24,
                    "min_confidence": 0.0,
                }
            }
        }

        result = apply_regime_v2_trend_gate(candidates, feature_vec, config)

        assert [c.model_name for c in result] == ["Momentum", "PriceAction"]
        assert result[0].metadata["regime_v2_trend_gate"] == "passed"

    def test_inactive_regime_policy_is_noop(self):
        feature_vec = FeatureVector(
            asset="BTCUSDT",
            timeframe="4h",
            timestamp=1000.0,
            features={
                "regime_v2": {
                    "evidence": {"trend_direction": "bull", "confidence": 0.7},
                    "policy": {"allow_trend_following": False, "trend_score": 0.5},
                }
            },
            bar_data={"close": 100.0},
        )
        candidates = [_make_candidate(model_name="Momentum", direction=-1)]
        config = {"overlays": {"regime_v2_trend_gate": {"enabled": True}}}

        result = apply_regime_v2_trend_gate(candidates, feature_vec, config)

        assert result is candidates

    def test_shadow_preview_runs_when_live_gate_disabled(self):
        feature_vec = FeatureVector(
            asset="BTCUSDT",
            timeframe="4h",
            timestamp=1000.0,
            features={
                "regime_v2": {
                    "evidence": {"trend_direction": "bull", "confidence": 0.7},
                    "policy": {"allow_trend_following": True, "trend_score": 0.5},
                }
            },
            bar_data={"close": 100.0},
        )
        candidates = [
            _make_candidate(model_name="Momentum", direction=1),
            _make_candidate(model_name="TrendFollowing", direction=-1),
            _make_candidate(model_name="PriceAction", direction=-1),
        ]
        config = {
            "overlays": {
                "regime_v2_trend_gate": {
                    "enabled": False,
                    "shadow_enabled": True,
                    "target_models": ["Momentum", "TrendFollowing"],
                    "min_trend_score": 0.24,
                }
            }
        }

        shadow_candidates, decision = preview_regime_v2_trend_gate(candidates, feature_vec, config)

        assert [c.model_name for c in shadow_candidates] == ["Momentum", "PriceAction"]
        assert decision["shadow_enabled"] is True
        assert decision["active"] is True
        assert decision["conflict_target_models"] == ["TrendFollowing"]

    def test_shadow_preview_disabled_is_noop(self, feature_vec):
        candidates = [_make_candidate(model_name="Momentum", direction=-1)]
        shadow_candidates, decision = preview_regime_v2_trend_gate(
            candidates,
            feature_vec,
            {"overlays": {"regime_v2_trend_gate": {"shadow_enabled": False}}},
        )

        assert shadow_candidates is candidates
        assert decision["reason"] == "shadow_disabled"

    def test_phase5a_shadow_default_uses_validated_subset_and_excludes_price_action(self):
        feature_vec = FeatureVector(
            asset="BTCUSDT",
            timeframe="4h",
            timestamp=1000.0,
            features={
                "regime_v2": {
                    "evidence": {"trend_direction": "bull", "confidence": 0.7, "uncertainty": 0.3},
                    "policy": {
                        "allow_trend_following": True,
                        "allow_breakout": True,
                        "allow_mean_reversion": True,
                        "trend_score": 0.5,
                        "breakout_score": 0.6,
                        "mean_reversion_score": 0.7,
                    },
                }
            },
            bar_data={"close": 100.0},
        )
        candidates = [
            _make_candidate(model_name="Momentum", direction=1),
            _make_candidate(model_name="TrendFollowing", direction=-1),
            _make_candidate(model_name="SqueezeBreakout", direction=1),
            _make_candidate(model_name="RegimePullbackScorer", direction=-1),
            _make_candidate(model_name="PriceAction", direction=1),
        ]
        config = {"overlays": {"regime_v2_trend_gate": {"shadow_enabled": True}}}

        shadow_candidates, decision = preview_regime_v2_trend_gate(candidates, feature_vec, config)

        assert [candidate.model_name for candidate in shadow_candidates] == [
            "Momentum",
            "SqueezeBreakout",
            "RegimePullbackScorer",
        ]
        assert decision["shadow_subset_name"] == "validated_phase5a_subset"
        assert decision["shadow_subset_only"] is True
        assert decision["include_non_target_models"] is False
        assert decision["active_playbooks"] == ["trend", "breakout", "mean_reversion"]
        assert "PriceAction" not in decision["target_models"]
        assert decision["candidate_playbooks"]["SqueezeBreakout"] == "breakout"
        assert decision["candidate_playbooks"]["RegimePullbackScorer"] == "mean_reversion"


# ---------------------------------------------------------------------------
# RegimeV2 Shadow Decision Log Tests
# ---------------------------------------------------------------------------

class TestRegimeV2ShadowDecisionLog:
    def test_shadow_decision_log_is_noop_when_disabled(self, tmp_path):
        path = tmp_path / "shadow.jsonl"
        result = persist_regime_v2_shadow_decision(
            {"baseline_selected_model": "Momentum"},
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000.0,
            config={"shadow_persist_enabled": False, "shadow_persist_path": str(path)},
            selected_count=1,
        )

        assert result is None
        assert not path.exists()

    def test_shadow_decision_log_writes_jsonl_when_enabled(self, tmp_path):
        path = tmp_path / "shadow" / "decisions.jsonl"
        result = persist_regime_v2_shadow_decision(
            {
                "baseline_selected_model": "PriceAction",
                "shadow_selected_model": "Momentum",
                "selection_changed": True,
                "reason": "shadow_changed_top_pick",
                "gate_active": True,
                "gate_reason": "active",
                "active_playbooks": ["trend"],
                "shadow_subset_name": "validated_phase5a_subset",
                "trend_score": 0.5,
                "confidence": 0.7,
                "candidate_playbooks": {"Momentum": "trend"},
                "trendline_context": {
                    "trendline_valid": 1.0,
                    "trendline_interaction": "NONE",
                    "trendline_market_position_state": "inside_channel",
                    "trendline_mean_normalized_quality": 0.72,
                    "trendline_ray_persistence_bias": 0.25,
                    "trendline_risk_context": "inside_channel_context",
                    "trendline_confidence_annotation": "neutral",
                    "trendline_annotation_reason": "price_inside_structural_channel",
                    "trendline_no_trade_warning": 0.0,
                },
            },
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000.0,
            config={"shadow_persist_enabled": True, "shadow_persist_path": str(path)},
            selected_count=2,
        )

        assert result == path
        record = json.loads(path.read_text().strip())
        assert record["schema_version"] == 1
        assert record["record_type"] == "regime_v2_shadow_decision"
        assert record["asset"] == "BTCUSDT"
        assert record["timeframe"] == "1h"
        assert record["baseline_selected_model"] == "PriceAction"
        assert record["shadow_selected_model"] == "Momentum"
        assert record["selection_changed"] is True
        assert record["active_playbooks"] == ["trend"]
        assert record["candidate_playbooks"] == {"Momentum": "trend"}
        assert record["trendline_valid"] == 1.0
        assert record["trendline_interaction"] == "NONE"
        assert record["trendline_market_position_state"] == "inside_channel"
        assert record["trendline_mean_normalized_quality"] == 0.72
        assert record["trendline_risk_context"] == "inside_channel_context"
        assert record["trendline_confidence_annotation"] == "neutral"
        assert record["trendline_annotation_reason"] == "price_inside_structural_channel"
        assert record["trendline_no_trade_warning"] == 0.0
        assert record["trendline_context"]["trendline_ray_persistence_bias"] == 0.25
        assert record["payload"]["shadow_subset_name"] == "validated_phase5a_subset"


# ---------------------------------------------------------------------------
# SelectionLayer.select() Integration Tests
# ---------------------------------------------------------------------------

class TestSelectionLayerSelect:
    def test_empty_candidates_returns_empty(self, feature_vec):
        """Empty model outputs → empty results."""
        results = self._run_select([], None, feature_vec)
        assert results == []

    def test_neutral_directions_skipped(self, feature_vec):
        """direction=0 model outputs are excluded."""
        outputs = [
            ModelOutput(
                model_name="neutral", asset="BTCUSDT", timeframe="1h",
                timestamp=1000.0, direction=0, conviction=0.9,
            ),
        ]
        results = self._run_select(outputs, None, feature_vec)
        assert results == []

    def test_mixed_threshold_and_scoring(self, feature_vec):
        """Both ModelOutput and ScoringOutput candidates are included."""
        model_outputs = [
            ModelOutput(
                model_name="squeeze", asset="BTCUSDT", timeframe="1h",
                timestamp=1000.0, direction=1, conviction=0.8,
            ),
        ]
        scoring_outputs = [
            ScoringOutput(
                model_name="alpha_v1", asset="BTCUSDT", timeframe="1h",
                timestamp=1000.0, edge_score=0.6, conviction=0.9,
            ),
        ]
        results = self._run_select(model_outputs, scoring_outputs, feature_vec)
        assert len(results) == 2
        source_types = {r.candidate.source_type for r in results}
        assert source_types == {"threshold", "scoring"}

    def test_scoring_outputs_none_handled(self, feature_vec):
        """scoring_outputs=None works correctly (Phase 1)."""
        model_outputs = [
            ModelOutput(
                model_name="squeeze", asset="BTCUSDT", timeframe="1h",
                timestamp=1000.0, direction=1, conviction=0.8,
            ),
        ]
        results = self._run_select(model_outputs, None, feature_vec)
        assert len(results) == 1
        assert results[0].candidate.source_type == "threshold"

    def test_selection_layer_applies_enabled_regime_v2_trend_gate(self):
        layer = object.__new__(SelectionLayer)
        layer.asset = "BTCUSDT"
        layer.timeframe = "4h"
        layer._strategy = TopKStrategy(OverlapPenalizedStrategy())
        layer._config = {
            "top_k": 5,
            "same_direction_penalty": 0.3,
            "max_penalty": 0.8,
            "overlays": {
                "regime_v2_trend_gate": {
                    "enabled": True,
                    "mode": "gated",
                    "target_models": ["Momentum", "TrendFollowing"],
                    "min_trend_score": 0.24,
                }
            },
        }
        feature_vec = FeatureVector(
            asset="BTCUSDT",
            timeframe="4h",
            timestamp=1000.0,
            features={
                "regime_v2": {
                    "evidence": {"trend_direction": "bull", "confidence": 0.7},
                    "policy": {"allow_trend_following": True, "trend_score": 0.5},
                }
            },
            bar_data={"close": 100.0},
        )
        model_outputs = [
            ModelOutput(model_name="Momentum", asset="BTCUSDT", timeframe="4h", timestamp=1000.0, direction=1, conviction=0.8),
            ModelOutput(model_name="TrendFollowing", asset="BTCUSDT", timeframe="4h", timestamp=1000.0, direction=-1, conviction=0.8),
            ModelOutput(model_name="PriceAction", asset="BTCUSDT", timeframe="4h", timestamp=1000.0, direction=-1, conviction=0.8),
        ]

        results = layer.select(model_outputs, None, feature_vec)

        assert {result.candidate.model_name for result in results} == {"Momentum", "PriceAction"}
        assert all(result.candidate.model_name != "TrendFollowing" for result in results)

    def test_selection_layer_shadow_mode_preserves_live_selection(self):
        layer = object.__new__(SelectionLayer)
        layer.asset = "BTCUSDT"
        layer.timeframe = "4h"
        layer._strategy = TopKStrategy(OverlapPenalizedStrategy())
        layer._config = {
            "top_k": 5,
            "same_direction_penalty": 0.3,
            "max_penalty": 0.8,
            "overlays": {
                "regime_v2_trend_gate": {
                    "enabled": False,
                    "shadow_enabled": True,
                    "shadow_log_enabled": False,
                    "mode": "gated",
                    "target_models": ["Momentum", "TrendFollowing"],
                    "min_trend_score": 0.24,
                }
            },
        }
        feature_vec = FeatureVector(
            asset="BTCUSDT",
            timeframe="4h",
            timestamp=1000.0,
            features={
                "regime_v2": {
                    "evidence": {"trend_direction": "bull", "confidence": 0.7},
                    "policy": {"allow_trend_following": True, "trend_score": 0.5},
                },
                "trendline": {
                    "trendline_valid": 1.0,
                    "trendline_interaction": "NONE",
                    "trendline_market_position_state": "inside_channel",
                    "trendline_risk_context": "inside_channel_context",
                    "trendline_confidence_annotation": "neutral",
                    "ignored_non_trendline_key": "not_copied",
                },
            },
            bar_data={"close": 100.0},
        )
        model_outputs = [
            ModelOutput(model_name="Momentum", asset="BTCUSDT", timeframe="4h", timestamp=1000.0, direction=1, conviction=0.8),
            ModelOutput(model_name="TrendFollowing", asset="BTCUSDT", timeframe="4h", timestamp=1000.0, direction=-1, conviction=0.8),
            ModelOutput(model_name="PriceAction", asset="BTCUSDT", timeframe="4h", timestamp=1000.0, direction=-1, conviction=0.8),
        ]

        results = layer.select(model_outputs, None, feature_vec)

        assert {result.candidate.model_name for result in results} == {"Momentum", "TrendFollowing", "PriceAction"}
        shadow = results[0].candidate.metadata["regime_v2_trend_gate_shadow"]
        assert shadow["baseline_selected_model"] == "Momentum"
        assert shadow["shadow_selected_model"] == "Momentum"
        assert shadow["selection_changed"] is False
        assert shadow["gate_active"] is True
        assert shadow["conflict_target_models"] == ["TrendFollowing"]
        assert shadow["active_playbooks"] == ["trend"]
        assert shadow["shadow_subset_name"] == "legacy_target_models"
        assert shadow["candidate_playbooks"]["Momentum"] == "trend"
        assert shadow["trendline_context"]["trendline_valid"] == 1.0
        assert shadow["trendline_context"]["trendline_market_position_state"] == "inside_channel"
        assert shadow["trendline_context"]["trendline_risk_context"] == "inside_channel_context"
        assert shadow["trendline_context"]["trendline_confidence_annotation"] == "neutral"
        assert "ignored_non_trendline_key" not in shadow["trendline_context"]
        assert shadow["breakout_score"] == 0.0
        assert shadow["mean_reversion_score"] == 0.0
        assert all("regime_v2_trend_gate" not in result.candidate.metadata for result in results)

    def test_selection_layer_persists_shadow_decision_when_enabled(self, tmp_path):
        layer = object.__new__(SelectionLayer)
        layer.asset = "BTCUSDT"
        layer.timeframe = "4h"
        layer._strategy = TopKStrategy(OverlapPenalizedStrategy())
        path = tmp_path / "shadow_decisions.jsonl"
        layer._config = {
            "top_k": 5,
            "same_direction_penalty": 0.3,
            "max_penalty": 0.8,
            "overlays": {
                "regime_v2_trend_gate": {
                    "enabled": False,
                    "shadow_enabled": True,
                    "shadow_log_enabled": False,
                    "shadow_persist_enabled": True,
                    "shadow_persist_path": str(path),
                    "mode": "gated",
                }
            },
        }
        feature_vec = FeatureVector(
            asset="BTCUSDT",
            timeframe="4h",
            timestamp=1000.0,
            features={
                "regime_v2": {
                    "evidence": {"trend_direction": "bull", "confidence": 0.7, "uncertainty": 0.3},
                    "policy": {
                        "allow_trend_following": True,
                        "allow_breakout": True,
                        "allow_mean_reversion": True,
                        "trend_score": 0.5,
                        "breakout_score": 0.6,
                        "mean_reversion_score": 0.7,
                    },
                }
            },
            bar_data={"close": 100.0},
        )
        model_outputs = [
            ModelOutput(model_name="PriceAction", asset="BTCUSDT", timeframe="4h", timestamp=1000.0, direction=1, conviction=0.99),
            ModelOutput(model_name="Momentum", asset="BTCUSDT", timeframe="4h", timestamp=1000.0, direction=1, conviction=0.8),
            ModelOutput(model_name="SqueezeBreakout", asset="BTCUSDT", timeframe="4h", timestamp=1000.0, direction=1, conviction=0.7),
        ]

        results = layer.select(model_outputs, None, feature_vec)

        assert results[0].candidate.model_name == "PriceAction"
        record = json.loads(path.read_text().strip())
        assert record["baseline_selected_model"] == "PriceAction"
        assert record["shadow_selected_model"] != "PriceAction"
        assert record["shadow_subset_name"] == "validated_phase5a_subset"
        assert record["selected_count"] == len(results)
        assert record["active_playbooks"] == ["trend", "breakout", "mean_reversion"]

    def test_selection_layer_phase5a_shadow_metadata_excludes_price_action_from_shadow_subset(self):
        layer = object.__new__(SelectionLayer)
        layer.asset = "BTCUSDT"
        layer.timeframe = "4h"
        layer._strategy = TopKStrategy(OverlapPenalizedStrategy())
        layer._config = {
            "top_k": 5,
            "same_direction_penalty": 0.3,
            "max_penalty": 0.8,
            "overlays": {
                "regime_v2_trend_gate": {
                    "enabled": False,
                    "shadow_enabled": True,
                    "shadow_log_enabled": False,
                    "mode": "gated",
                }
            },
        }
        feature_vec = FeatureVector(
            asset="BTCUSDT",
            timeframe="4h",
            timestamp=1000.0,
            features={
                "regime_v2": {
                    "evidence": {"trend_direction": "bull", "confidence": 0.7, "uncertainty": 0.3},
                    "policy": {
                        "allow_trend_following": True,
                        "allow_breakout": True,
                        "allow_mean_reversion": True,
                        "trend_score": 0.5,
                        "breakout_score": 0.6,
                        "mean_reversion_score": 0.7,
                    },
                }
            },
            bar_data={"close": 100.0},
        )
        model_outputs = [
            ModelOutput(model_name="PriceAction", asset="BTCUSDT", timeframe="4h", timestamp=1000.0, direction=1, conviction=0.99),
            ModelOutput(model_name="Momentum", asset="BTCUSDT", timeframe="4h", timestamp=1000.0, direction=1, conviction=0.8),
            ModelOutput(model_name="TrendFollowing", asset="BTCUSDT", timeframe="4h", timestamp=1000.0, direction=-1, conviction=0.8),
            ModelOutput(model_name="SqueezeBreakout", asset="BTCUSDT", timeframe="4h", timestamp=1000.0, direction=1, conviction=0.7),
            ModelOutput(model_name="RegimePullbackScorer", asset="BTCUSDT", timeframe="4h", timestamp=1000.0, direction=-1, conviction=0.6),
        ]

        results = layer.select(model_outputs, None, feature_vec)

        assert results[0].candidate.model_name == "PriceAction"
        shadow = results[0].candidate.metadata["regime_v2_trend_gate_shadow"]
        assert shadow["baseline_selected_model"] == "PriceAction"
        assert shadow["shadow_subset_name"] == "validated_phase5a_subset"
        assert shadow["shadow_subset_only"] is True
        assert shadow["include_non_target_models"] is False
        assert shadow["shadow_selected_model"] != "PriceAction"
        assert shadow["active_playbooks"] == ["trend", "breakout", "mean_reversion"]
        assert "PriceAction" not in shadow["target_models"]
        assert shadow["candidate_playbooks"]["SqueezeBreakout"] == "breakout"
        assert shadow["candidate_playbooks"]["RegimePullbackScorer"] == "mean_reversion"
        assert all("regime_v2_trend_gate" not in result.candidate.metadata for result in results)

    @staticmethod
    def _run_select(model_outputs, scoring_outputs, feature_vec):
        """Helper that bypasses config loading by calling normalization + strategy directly."""
        from libs.selection.strategies import TopKStrategy, OverlapPenalizedStrategy

        candidates = []
        for mo in model_outputs:
            if mo.direction != 0:
                candidates.append(SelectionLayer.normalize_model_output(mo))
        if scoring_outputs:
            for so in scoring_outputs:
                candidates.append(SelectionLayer.normalize_scoring_output(so))
        if not candidates:
            return []

        config = {
            "top_k": 3,
            "same_direction_penalty": 0.3,
            "max_penalty": 0.8,
        }
        strategy = TopKStrategy(OverlapPenalizedStrategy())
        return strategy.select(candidates, feature_vec, config)


# ---------------------------------------------------------------------------
# Selection Config Safety Tests
# ---------------------------------------------------------------------------

class TestSelectionConfigSafety:
    def test_phase5d_rollout_enables_shadow_only_for_expected_pairs(self):
        selection = yaml.safe_load(Path("configs/selection.yaml").read_text())["selection"]
        assets = selection["assets"]
        expected = {
            ("BTCUSDT", "4h"),
            ("ETHUSDT", "4h"),
            ("SOLUSDT", "4h"),
            ("BNBUSDT", "1h"),
        }

        enabled_pairs = set()
        for asset, asset_cfg in assets.items():
            if asset == "default":
                continue
            for timeframe, tf_cfg in asset_cfg.get("timeframes", {}).items():
                gate = tf_cfg.get("overlays", {}).get("regime_v2_trend_gate", {})
                if gate.get("shadow_enabled") or gate.get("shadow_persist_enabled"):
                    enabled_pairs.add((asset, timeframe))
                    assert gate["enabled"] is False
                    assert gate["shadow_enabled"] is True
                    assert gate["shadow_persist_enabled"] is True
                    assert gate["shadow_subset_only"] is True
                    assert gate["shadow_include_non_targets"] is False
                    assert "PriceAction" not in gate["shadow_target_models"]

        assert enabled_pairs == expected

    def test_phase5d_rollout_asset_defaults_remain_disabled(self):
        selection = yaml.safe_load(Path("configs/selection.yaml").read_text())["selection"]
        rollout_assets = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

        for asset in rollout_assets:
            default_tf = selection["assets"][asset]["timeframes"]["default"]
            gate = default_tf["overlays"]["regime_v2_trend_gate"]
            assert gate["enabled"] is False
            assert gate["shadow_enabled"] is False
            assert gate["shadow_persist_enabled"] is False
            assert "PriceAction" not in gate["shadow_target_models"]


# ---------------------------------------------------------------------------
# Config Fallback Chain (unit-level — mocked ConfigManager)
# ---------------------------------------------------------------------------

class TestConfigFallback:
    def test_default_config_loads(self, monkeypatch, feature_vec):
        """Ensure SelectionLayer can initialize with defaults from selection.yaml."""
        # Patch ConfigManager to return our test config
        mock_state = {
            "selection": {
                "assets": {
                    "default": {
                        "timeframes": {
                            "default": {
                                "strategy": "conviction_weighted",
                                "top_k": 5,
                                "min_edge_threshold": 0.1,
                                "same_direction_penalty": 0.2,
                                "max_penalty": 0.6,
                            }
                        }
                    }
                }
            }
        }

        from libs.common.config import ConfigManager

        monkeypatch.setattr(ConfigManager, "__new__", lambda cls, *a, **kw: object.__new__(cls))
        monkeypatch.setattr(ConfigManager, "__init__", lambda self, *a, **kw: None)
        monkeypatch.setattr(ConfigManager, "register_file", lambda self, f: None)
        monkeypatch.setattr(
            ConfigManager,
            "get",
            lambda self, key, default=None: mock_state.get(key, default),
        )

        layer = SelectionLayer("BTCUSDT", "1h")
        assert layer._config["top_k"] == 5
        assert layer._config["strategy"] == "conviction_weighted"
        assert isinstance(layer._strategy, ConvictionWeightedStrategy)
