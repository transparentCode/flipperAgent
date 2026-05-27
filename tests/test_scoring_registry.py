"""Tests for ScoringModelRegistry."""

from __future__ import annotations

import pytest

from libs.models.scoring_base import ScoringModel
from libs.models.scoring_registry import ScoringModelRegistry
from libs.models.base import ModelMeta
from libs.contracts.signal import ParamDef, ScoringOutput
from libs.contracts.schemas import FeatureVector

import pandas as pd


# ---------------------------------------------------------------------------
# Fixture: mock scoring model
# ---------------------------------------------------------------------------


class _MockScoringModel(ScoringModel):
    meta = ModelMeta(
        name="MockScorer",
        required_indicators=[],
        required_fields=[],
    )

    def evaluate(self, features: FeatureVector) -> ScoringOutput:
        return ScoringOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            edge_score=1.0,
            conviction=0.5,
        )

    def batch_evaluate(self, feature_df: pd.DataFrame) -> pd.Series:
        return pd.Series(1.0, index=feature_df.index)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestScoringModelRegistry:
    def setup_method(self):
        # Snapshot and restore registry state to avoid side effects
        self._orig = dict(ScoringModelRegistry._registry)

    def teardown_method(self):
        ScoringModelRegistry._registry = self._orig

    def test_register_and_get(self):
        ScoringModelRegistry.register("TestMock")(_MockScoringModel)
        cls = ScoringModelRegistry.get("TestMock")
        assert cls is _MockScoringModel

    def test_list_all(self):
        ScoringModelRegistry.register("ListMock")(_MockScoringModel)
        assert "ListMock" in ScoringModelRegistry.list_all()

    def test_unknown_raises_key_error(self):
        with pytest.raises(KeyError, match="not found"):
            ScoringModelRegistry.get("NoSuchModel_XYZ")

    def test_decorator_returns_class_unchanged(self):
        decorated = ScoringModelRegistry.register("DecoratorTest")(_MockScoringModel)
        assert decorated is _MockScoringModel

    def test_register_overwrites(self):
        ScoringModelRegistry.register("OverwriteTest")(_MockScoringModel)

        class _AnotherMock(_MockScoringModel):
            pass

        ScoringModelRegistry.register("OverwriteTest")(_AnotherMock)
        assert ScoringModelRegistry.get("OverwriteTest") is _AnotherMock
