"""Tests for ScoringModelRegistry (backward-compat wrapper over ModelRegistry)."""

from __future__ import annotations

import warnings

import pytest

from libs.models.scoring_base import ScoringModel
from libs.models.scoring_registry import ScoringModelRegistry
from libs.models.registry import ModelRegistry
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
        model_type="scoring",
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
        # Snapshot and restore the unified ModelRegistry state
        self._orig = dict(ModelRegistry._registry)

    def teardown_method(self):
        ModelRegistry._registry = self._orig

    def test_register_and_get(self):
        ScoringModelRegistry.register("TestMock")(_MockScoringModel)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            cls = ScoringModelRegistry.get("TestMock")
        assert cls is _MockScoringModel

    def test_list_all(self):
        ScoringModelRegistry.register("ListMock")(_MockScoringModel)
        assert "ListMock" in ScoringModelRegistry.list_all()

    def test_unknown_raises_key_error(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
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
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            assert ScoringModelRegistry.get("OverwriteTest") is _AnotherMock

    def test_get_emits_deprecation_warning(self):
        ScoringModelRegistry.register("DepWarnTest")(_MockScoringModel)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ScoringModelRegistry.get("DepWarnTest")
            assert any(issubclass(x.category, DeprecationWarning) for x in w)

    def test_delegates_to_model_registry(self):
        """Registering via ScoringModelRegistry stores in ModelRegistry."""
        ScoringModelRegistry.register("DelegateTest")(_MockScoringModel)
        assert ModelRegistry.get("DelegateTest") is _MockScoringModel
