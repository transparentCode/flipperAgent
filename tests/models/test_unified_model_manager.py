from __future__ import annotations

import pytest

from libs.contracts.signal import FeatureVector, ParamDef, ScoringOutput
from libs.contracts.strategy_model import (
    ModelDecision,
    ModelExecutionContext,
    ModelInputContract,
    ModelTriggerSpec,
    StrategyModelSpec,
)
from libs.models.base import BaseModel, ModelMeta
from libs.models.registry import ModelRegistry
from libs.models.scoring_base import ScoringModel
from libs.models.strategy_model_v2 import StrategyModelV2
from libs.models.strategy_registry import StrategyModelRegistry

from apps.strategy_app.models.unified_model_manager import UnifiedModelManager


class FakeConfigManager:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def register_file(self, _name: str) -> None:
        return None

    def get(self, key_path: str, default=None):
        if not key_path:
            return self.payload
        current = self.payload
        for key in key_path.split("."):
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current


@StrategyModelRegistry.register("UnitCanonicalModel")
class UnitCanonicalModel(StrategyModelV2):
    spec = StrategyModelSpec(name="UnitCanonicalModel")
    trigger = ModelTriggerSpec(decision_timeframe="1h", base_timeframe="1m")
    inputs = ModelInputContract(required_indicators=["RSI"], required_fields=["RSI.value"])
    param_schema = {"bias": ParamDef(type="float", default=0.1, low=0.0, high=1.0)}

    def evaluate(self, context: ModelExecutionContext) -> ModelDecision:
        return ModelDecision(
            model_name=self.spec.name,
            asset=context.asset,
            decision_timeframe=self.trigger.decision_timeframe,
            trigger_timeframe=self.trigger.trigger_timeframe or self.trigger.decision_timeframe,
            timestamp=context.timestamp,
            score=float(context.feature_vector.features.get("score", 0.0)) + self.params["bias"],
            direction_hint=1,
            conviction=0.5,
            metadata={"source": "canonical"},
        )


@ModelRegistry.register("UnitLegacyDirectionModel")
class UnitLegacyDirectionModel(BaseModel):
    meta = ModelMeta(
        name="UnitLegacyDirectionModel",
        required_indicators=["EMA"],
        required_fields=["EMA.value"],
        hyperparameter_schema={"lookback": ParamDef(type="int", default=10, low=1, high=100)},
        min_history_bars=10,
    )

    def evaluate(self, features: FeatureVector):
        from libs.contracts.signal import ModelOutput

        return ModelOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            direction=1,
            conviction=0.8,
            metadata={"source": "legacy_direction"},
        )

    def _batch_evaluate_impl(self, feature_df):
        raise NotImplementedError


@ModelRegistry.register("UnitLegacyScoringModel")
class UnitLegacyScoringModel(ScoringModel):
    meta = ModelMeta(
        name="UnitLegacyScoringModel",
        required_indicators=["ATR"],
        required_fields=["ATR.value"],
        hyperparameter_schema={"weight": ParamDef(type="float", default=0.2, low=0.0, high=1.0)},
        min_history_bars=12,
        model_type="scoring",
    )

    def evaluate(self, features: FeatureVector) -> ScoringOutput:
        return ScoringOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            edge_score=-0.25,
            conviction=0.4,
            metadata={"source": "legacy_scoring"},
        )

    def _batch_evaluate_impl(self, feature_df):
        raise NotImplementedError


def _manager(config_payload: dict, *, bridge_legacy_roots: bool = True) -> UnifiedModelManager:
    manager = FakeConfigManager({
        **config_payload,
        "features": {
            "assets": {
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "RSI": {},
                            "EMA": {},
                            "ATR": {},
                        }
                    }
                }
            }
        },
        "engineered_features": {"assets": {"BTCUSDT": {"timeframes": {"1h": {}}}}},
    })
    return UnifiedModelManager(
        "BTCUSDT",
        "1h",
        config_manager=manager,
        bridge_legacy_roots=bridge_legacy_roots,
    )


def test_unified_model_manager_loads_canonical_root() -> None:
    payload = {
        "strategy_models": {
            "assets": {
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "UnitCanonicalModel": {
                                "enabled": True,
                                "params": {"bias": 0.3},
                            }
                        }
                    }
                }
            }
        }
    }
    manager = _manager(payload, bridge_legacy_roots=False)
    assert [model.spec.name for model in manager.models] == ["UnitCanonicalModel"]
    assert manager.runtime_specs["UnitCanonicalModel"].decision_timeframe == "1h"


def test_unified_model_manager_bridges_legacy_roots() -> None:
    payload = {
        "models": {
            "assets": {
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "UnitLegacyDirectionModel": {
                                "enabled": True,
                                "migration_mode": "legacy",
                                "params": {},
                            }
                        }
                    }
                }
            }
        },
        "scoring_models": {
            "assets": {
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "UnitLegacyScoringModel": {
                                "enabled": True,
                                "migration_mode": "native_scoring",
                                "params": {},
                            }
                        }
                    }
                }
            }
        },
    }
    manager = _manager(payload, bridge_legacy_roots=True)
    names = sorted(model.spec.name for model in manager.models)
    assert names == ["UnitLegacyDirectionModel", "UnitLegacyScoringModel"]


def test_unified_model_manager_evaluate() -> None:
    payload = {
        "strategy_models": {
            "assets": {
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "UnitCanonicalModel": {
                                "enabled": True,
                                "params": {"bias": 0.2},
                            }
                        }
                    }
                }
            }
        }
    }
    manager = _manager(payload, bridge_legacy_roots=False)
    outputs = manager.evaluate(
        FeatureVector(
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1700000000.0,
            features={"score": 0.4},
            bar_data={},
        )
    )
    assert len(outputs) == 1
    assert outputs[0].model_name == "UnitCanonicalModel"
    assert outputs[0].score == pytest.approx(0.6)
