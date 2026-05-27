"""Tests for the SelectionLayer, strategies, and normalization."""

import pytest

from libs.contracts.signal import (
    FeatureVector,
    ModelOutput,
    ScoringOutput,
    SelectionCandidate,
    SelectionResult,
)
from libs.selection.base import SelectionStrategy
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
