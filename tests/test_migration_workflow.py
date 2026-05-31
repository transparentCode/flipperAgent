"""Tests for legacy model migration workflow — ModelManager partitioning and StrategyWorker routing."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from libs.contracts.schemas import FeatureVector, ModelOutput
from libs.contracts.signal import ScoringOutput
from libs.models.base import BaseModel, ModelMeta
from libs.models.legacy_adapter import LegacyScoringAdapter
from libs.models.registry import ModelRegistry
from libs.contracts.schemas import ParamDef


# ── Stub model for testing (avoids depending on real model internals) ──

_STUB_META = ModelMeta(
    name="StubModel",
    required_indicators=["RSI"],
    required_fields=["RSI"],
    hyperparameter_schema={
        "threshold": ParamDef(type="float", default=0.5, low=0.0, high=1.0),
    },
)


class _StubModel(BaseModel):
    meta = _STUB_META

    def evaluate(self, features: FeatureVector) -> ModelOutput:
        return ModelOutput(
            model_name="StubModel",
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            direction=1,
            conviction=0.8,
            metadata={"stub": True},
        )

    def _batch_evaluate_impl(self, feature_df):
        import pandas as pd
        return pd.Series([1] * len(feature_df), index=feature_df.index)


def _fv():
    return FeatureVector(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1000.0,
        features={"RSI": 50},
        bar_data={"close": 100, "high": 110, "low": 90, "volume": 1000},
    )


# ── Register the stub temporarily ─────────────────────────────────────

@pytest.fixture(autouse=True)
def _register_stub():
    """Register StubModel in the ModelRegistry for the duration of each test."""
    ModelRegistry._registry["StubModel"] = _StubModel
    yield
    ModelRegistry._registry.pop("StubModel", None)


# ── Mock ConfigManager ────────────────────────────────────────────────

def _make_model_manager(model_configs: dict[str, Any]):
    """Create a ModelManager with mocked config returning the given model entries."""
    from apps.strategy_app.model_manager import ModelManager

    with patch.object(ModelManager, "_resolve_config_node") as mock_resolve:
        def side_effect(root_key: str):
            if root_key == "models":
                return model_configs
            return {}
        mock_resolve.side_effect = side_effect
        mgr = ModelManager.__new__(ModelManager)
        mgr.asset = "BTCUSDT"
        mgr.timeframe = "1h"
        mgr.config_mgr = MagicMock()
        mgr.models = []
        mgr.adapted_models = []
        mgr.scoring_models = []
        mgr.shadow_models = []
        mgr._resolve_config_node = mock_resolve
        mgr._load_models()
    return mgr


# ── 1. Backward compatibility: absent migration_mode defaults to legacy ──

class TestDefaultLegacy:
    def test_absent_migration_mode_loads_legacy(self):
        mgr = _make_model_manager({
            "StubModel": {"enabled": True, "params": {}},
        })
        assert len(mgr.models) == 1
        assert len(mgr.adapted_models) == 0
        assert len(mgr.shadow_models) == 0
        assert isinstance(mgr.models[0], _StubModel)

    def test_explicit_legacy_loads_legacy(self):
        mgr = _make_model_manager({
            "StubModel": {"enabled": True, "migration_mode": "legacy", "params": {}},
        })
        assert len(mgr.models) == 1
        assert len(mgr.adapted_models) == 0


# ── 2. Adapted mode ───────────────────────────────────────────────────

class TestAdaptedMode:
    def test_adapted_loads_into_adapted_models(self):
        mgr = _make_model_manager({
            "StubModel": {"enabled": True, "migration_mode": "adapted", "params": {}},
        })
        assert len(mgr.models) == 0
        assert len(mgr.adapted_models) == 1
        assert isinstance(mgr.adapted_models[0], LegacyScoringAdapter)

    def test_adapted_with_comparison_logging_loads_shadow(self):
        mgr = _make_model_manager({
            "StubModel": {
                "enabled": True,
                "migration_mode": "adapted",
                "comparison_logging": True,
                "params": {},
            },
        })
        assert len(mgr.adapted_models) == 1
        assert len(mgr.shadow_models) == 1
        # Shadow must be separate instance
        assert mgr.adapted_models[0]._wrapped is not mgr.shadow_models[0]

    def test_adapted_without_comparison_logging_no_shadow(self):
        mgr = _make_model_manager({
            "StubModel": {
                "enabled": True,
                "migration_mode": "adapted",
                "comparison_logging": False,
                "params": {},
            },
        })
        assert len(mgr.adapted_models) == 1
        assert len(mgr.shadow_models) == 0


# ── 3. Native scoring mode ───────────────────────────────────────────

class TestNativeScoringMode:
    def test_native_scoring_skips_model(self):
        mgr = _make_model_manager({
            "StubModel": {"enabled": True, "migration_mode": "native_scoring", "params": {}},
        })
        assert len(mgr.models) == 0
        assert len(mgr.adapted_models) == 0
        assert len(mgr.shadow_models) == 0


# ── 4. Unrecognized migration_mode defaults to legacy ─────────────────

class TestUnrecognizedMode:
    def test_unrecognized_mode_defaults_legacy(self):
        mgr = _make_model_manager({
            "StubModel": {"enabled": True, "migration_mode": "bogus", "params": {}},
        })
        assert len(mgr.models) == 1
        assert len(mgr.adapted_models) == 0


# ── 5. evaluate_adapted returns ScoringOutput ─────────────────────────

class TestEvaluateAdapted:
    def test_returns_scoring_output_list(self):
        mgr = _make_model_manager({
            "StubModel": {"enabled": True, "migration_mode": "adapted", "params": {}},
        })
        fv = _fv()
        results = mgr.evaluate_adapted(fv)
        assert len(results) == 1
        assert isinstance(results[0], ScoringOutput)
        assert results[0].model_name == "StubModel"
        assert results[0].edge_score == 1 * 0.8  # direction=1, conviction=0.8

    def test_evaluate_adapted_empty_when_no_adapted(self):
        mgr = _make_model_manager({
            "StubModel": {"enabled": True, "migration_mode": "legacy", "params": {}},
        })
        fv = _fv()
        results = mgr.evaluate_adapted(fv)
        assert results == []


# ── 6. evaluate_shadow returns ModelOutput ────────────────────────────

class TestEvaluateShadow:
    def test_returns_model_output_list(self):
        mgr = _make_model_manager({
            "StubModel": {
                "enabled": True,
                "migration_mode": "adapted",
                "comparison_logging": True,
                "params": {},
            },
        })
        fv = _fv()
        results = mgr.evaluate_shadow(fv)
        assert len(results) == 1
        assert isinstance(results[0], ModelOutput)

    def test_evaluate_shadow_empty_when_no_comparison(self):
        mgr = _make_model_manager({
            "StubModel": {"enabled": True, "migration_mode": "adapted", "params": {}},
        })
        fv = _fv()
        results = mgr.evaluate_shadow(fv)
        assert results == []


# ── 7. Shadow and adapted are separate instances ─────────────────────

class TestSeparateInstances:
    def test_no_shared_state_between_adapted_and_shadow(self):
        mgr = _make_model_manager({
            "StubModel": {
                "enabled": True,
                "migration_mode": "adapted",
                "comparison_logging": True,
                "params": {},
            },
        })
        adapted_wrapped = mgr.adapted_models[0]._wrapped
        shadow = mgr.shadow_models[0]
        assert adapted_wrapped is not shadow
        assert adapted_wrapped.params == shadow.params


# ── 8. Feature coverage validates all three lists ────────────────────

class TestFeatureCoverage:
    def test_validates_adapted_models(self):
        mgr = _make_model_manager({
            "StubModel": {"enabled": True, "migration_mode": "adapted", "params": {}},
        })
        # RSI is required by StubModel; providing it should not raise
        mgr.validate_feature_coverage(available_features={"RSI"})

    def test_missing_features_raises_for_adapted(self):
        from libs.common.exceptions import ConfigurationError
        mgr = _make_model_manager({
            "StubModel": {"enabled": True, "migration_mode": "adapted", "params": {}},
        })
        with pytest.raises(ConfigurationError):
            mgr.validate_feature_coverage(available_features={"MACD"})


# ── 9. Config rollback: adapted → legacy restores behavior ──────────

class TestConfigRollback:
    def test_rollback_adapted_to_legacy(self):
        # Start with adapted
        mgr_adapted = _make_model_manager({
            "StubModel": {"enabled": True, "migration_mode": "adapted", "params": {}},
        })
        assert len(mgr_adapted.adapted_models) == 1
        assert len(mgr_adapted.models) == 0

        # Rollback to legacy
        mgr_legacy = _make_model_manager({
            "StubModel": {"enabled": True, "migration_mode": "legacy", "params": {}},
        })
        assert len(mgr_legacy.adapted_models) == 0
        assert len(mgr_legacy.models) == 1


# ── 10. Mixed models ────────────────────────────────────────────────

class TestMixedModels:
    def test_mixed_legacy_and_adapted(self):
        """Different models in different modes — one legacy, one adapted."""
        # Register a second stub
        _STUB2_META = ModelMeta(
            name="StubModel2",
            required_indicators=["RSI"],
            required_fields=["RSI"],
            hyperparameter_schema={
                "threshold": ParamDef(type="float", default=0.5, low=0.0, high=1.0),
            },
        )

        class _StubModel2(BaseModel):
            meta = _STUB2_META

            def evaluate(self, features):
                return ModelOutput(
                    model_name="StubModel2",
                    asset=features.asset,
                    timeframe=features.timeframe,
                    timestamp=features.timestamp,
                    direction=-1,
                    conviction=0.6,
                )

            def _batch_evaluate_impl(self, feature_df):
                import pandas as pd
                return pd.Series([-1] * len(feature_df), index=feature_df.index)

        ModelRegistry._registry["StubModel2"] = _StubModel2
        try:
            mgr = _make_model_manager({
                "StubModel": {"enabled": True, "migration_mode": "legacy", "params": {}},
                "StubModel2": {"enabled": True, "migration_mode": "adapted", "params": {}},
            })
            assert len(mgr.models) == 1
            assert mgr.models[0].meta.name == "StubModel"
            assert len(mgr.adapted_models) == 1
            assert mgr.adapted_models[0].meta.name == "StubModel2"
        finally:
            ModelRegistry._registry.pop("StubModel2", None)


# ── 11. Comparison logging ──────────────────────────────────────────

class TestComparisonLogging:
    def test_match_true_for_correct_adapter(self):
        """Shadow and adapted outputs should produce match=True."""
        from apps.strategy_app.strategy_worker import StrategyWorker

        adapted_out = ScoringOutput(
            model_name="StubModel",
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000.0,
            edge_score=0.8,
            conviction=0.8,
            metadata={"_adapted": True, "_original_direction": 1},
        )
        shadow_out = ModelOutput(
            model_name="StubModel",
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000.0,
            direction=1,
            conviction=0.8,
        )
        worker = StrategyWorker.__new__(StrategyWorker)
        worker.asset = "BTCUSDT"
        worker.timeframe = "1h"

        # Should not raise; logs match=True
        with patch("apps.strategy_app.strategy_worker.logger") as mock_logger:
            worker._log_migration_comparison([adapted_out], [shadow_out])
            # Verify logger.info was called with match=True
            call_kwargs = mock_logger.info.call_args
            assert call_kwargs is not None
            # structlog-style: positional args + kwargs
            assert call_kwargs[1].get("match") is True

    def test_mismatch_logs_warning(self):
        """Mismatched edge scores should trigger a warning."""
        from apps.strategy_app.strategy_worker import StrategyWorker

        adapted_out = ScoringOutput(
            model_name="StubModel",
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000.0,
            edge_score=0.5,  # Deliberately wrong
            conviction=0.8,
        )
        shadow_out = ModelOutput(
            model_name="StubModel",
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000.0,
            direction=1,
            conviction=0.8,
        )
        worker = StrategyWorker.__new__(StrategyWorker)
        worker.asset = "BTCUSDT"
        worker.timeframe = "1h"

        with patch("apps.strategy_app.strategy_worker.logger") as mock_logger:
            worker._log_migration_comparison([adapted_out], [shadow_out])
            assert mock_logger.warning.called

    def test_no_shadow_output_skips_logging(self):
        """If no shadow output matches, no comparison is logged."""
        from apps.strategy_app.strategy_worker import StrategyWorker

        adapted_out = ScoringOutput(
            model_name="StubModel",
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000.0,
            edge_score=0.8,
            conviction=0.8,
        )
        worker = StrategyWorker.__new__(StrategyWorker)
        worker.asset = "BTCUSDT"
        worker.timeframe = "1h"

        with patch("apps.strategy_app.strategy_worker.logger") as mock_logger:
            worker._log_migration_comparison([adapted_out], [])
            mock_logger.info.assert_not_called()
