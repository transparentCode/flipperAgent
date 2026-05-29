"""Tests for Phase 1D: ScoringOutput, SelectionCandidate, SelectionResult contracts
and ScoringModel ABC."""

from __future__ import annotations

import pytest
import pandas as pd

from libs.contracts.signal import (
    ScoringOutput,
    SelectionCandidate,
    SelectionResult,
)
from libs.models.scoring_base import ScoringModel
from libs.models.base import ModelMeta
from libs.contracts.signal import ParamDef


# ---------------------------------------------------------------------------
# Contract serialization tests
# ---------------------------------------------------------------------------


class TestScoringOutput:
    def test_roundtrip(self):
        so = ScoringOutput(
            model_name="test_model",
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1700000000.0,
            edge_score=0.42,
            conviction=0.8,
            metadata={"reason": "strong_trend"},
        )
        data = so.model_dump()
        restored = ScoringOutput.model_validate(data)
        assert restored.model_name == "test_model"
        assert restored.edge_score == 0.42
        assert restored.conviction == 0.8
        assert restored.metadata == {"reason": "strong_trend"}

    def test_defaults(self):
        so = ScoringOutput(
            model_name="m",
            asset="ETH",
            timeframe="4h",
            timestamp=0.0,
            edge_score=-1.5,
        )
        assert so.conviction == 1.0
        assert so.metadata == {}

    def test_conviction_bounds(self):
        with pytest.raises(Exception):
            ScoringOutput(
                model_name="m", asset="X", timeframe="1h",
                timestamp=0.0, edge_score=0.0, conviction=1.5,
            )


class TestSelectionCandidate:
    def test_roundtrip(self):
        sc = SelectionCandidate(
            model_name="sb",
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1700000000.0,
            direction=1,
            edge_score=0.3,
            conviction=0.9,
            source_type="threshold",
        )
        data = sc.model_dump()
        restored = SelectionCandidate.model_validate(data)
        assert restored.direction == 1
        assert restored.source_type == "threshold"

    def test_scoring_source_type(self):
        sc = SelectionCandidate(
            model_name="scorer",
            asset="ETH",
            timeframe="4h",
            timestamp=0.0,
            direction=-1,
            edge_score=0.7,
            conviction=0.5,
            source_type="scoring",
        )
        assert sc.source_type == "scoring"

    def test_invalid_source_type(self):
        with pytest.raises(Exception):
            SelectionCandidate(
                model_name="m", asset="X", timeframe="1h",
                timestamp=0.0, direction=0, edge_score=0.0,
                conviction=0.5, source_type="invalid",
            )


class TestSelectionResult:
    def test_roundtrip_with_nested_candidate(self):
        candidate = SelectionCandidate(
            model_name="sb",
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1700000000.0,
            direction=1,
            edge_score=0.5,
            conviction=0.9,
            source_type="threshold",
        )
        sr = SelectionResult(
            candidate=candidate,
            rank=1,
            selection_score=0.85,
            penalties={"overlap": -0.05, "correlation": -0.10},
        )
        data = sr.model_dump()
        restored = SelectionResult.model_validate(data)
        assert restored.rank == 1
        assert restored.selection_score == 0.85
        assert restored.candidate.model_name == "sb"
        assert restored.penalties["overlap"] == -0.05


# ---------------------------------------------------------------------------
# ScoringModel ABC tests
# ---------------------------------------------------------------------------


class _DummyScoringModel(ScoringModel):
    """Concrete subclass for testing."""

    meta = ModelMeta(
        name="dummy_scorer",
        required_indicators=["RSI", "ATR"],
        required_fields=["RSI.value", "ATR.value"],
        hyperparameter_schema={
            "threshold": ParamDef(type="float", default=0.5, low=0.0, high=1.0),
        },
    )

    def evaluate(self, features) -> ScoringOutput:
        return ScoringOutput(
            model_name=self.meta.name,
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=0.0,
            edge_score=0.42,
        )

    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
        return pd.Series(0.0, index=feature_df.index)


class TestScoringModelABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            ScoringModel({})  # type: ignore[abstract]

    def test_concrete_subclass(self):
        model = _DummyScoringModel({})
        assert model.params["threshold"] == 0.5

    def test_evaluate(self):
        model = _DummyScoringModel({})
        result = model.evaluate(None)
        assert isinstance(result, ScoringOutput)
        assert result.edge_score == 0.42

    def test_batch_evaluate(self):
        model = _DummyScoringModel({})
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = model.batch_evaluate(df)
        assert len(result) == 3

    def test_validate_features_all_present(self):
        model = _DummyScoringModel({})
        missing = model.validate_features({"RSI", "ATR", "MACD"})
        assert missing == []

    def test_validate_features_missing(self):
        model = _DummyScoringModel({})
        missing = model.validate_features({"RSI"})
        assert missing == ["ATR"]

    def test_validate_required_fields_present(self):
        model = _DummyScoringModel({})
        missing = model.validate_required_fields({"RSI", "ATR"})
        assert missing == []

    def test_validate_required_fields_missing(self):
        model = _DummyScoringModel({})
        missing = model.validate_required_fields({"RSI"})
        assert "ATR.value" in missing

    def test_param_override(self):
        model = _DummyScoringModel({"threshold": 0.9})
        assert model.params["threshold"] == 0.9
