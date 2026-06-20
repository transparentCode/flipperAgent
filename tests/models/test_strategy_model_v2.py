from __future__ import annotations

from typing import Any

from libs.contracts.signal import FeatureVector, ModelOutput, ParamDef, ScoringOutput
from libs.contracts.strategy_model import (
    ModelExecutionContext,
    ModelInputContract,
    ModelTriggerSpec,
    StrategyModelSpec,
)
from libs.models.base import BaseModel, ModelMeta
from libs.models.kyle_tfi.strategy_v2 import KyleTFIV2
from libs.models.mean_reversion.strategy_v2 import MeanReversionV2
from libs.models.momentum.strategy_v2 import MomentumV2
from libs.models.price_action.strategy_v2 import PriceActionV2
from libs.models.scoring_base import ScoringModel
from libs.models.strategy_adapters import LegacyBaseModelAdapter, LegacyScoringModelAdapter
from libs.models.strategy_model_v2 import StrategyModelV2
from libs.models.vpin_kyle.strategy_v2 import VPINKyleV2


class DummyStrategyModel(StrategyModelV2):
    spec = StrategyModelSpec(name="dummy_v2", private_feature_engineering=True)
    trigger = ModelTriggerSpec(decision_timeframe="1h", base_timeframe="1m")
    inputs = ModelInputContract(
        required_indicators=["RSI", "ATR"],
        required_fields=["RSI.value", "ATR.value"],
        required_context_profiles=["regime"],
        warmup_bars=32,
    )
    param_schema = {
        "threshold": ParamDef(type="float", default=0.4, low=0.0, high=1.0),
    }

    def evaluate(self, context: ModelExecutionContext):
        score = float(context.feature_vector.features.get("score", 0.0))
        direction = 1 if score > 0 else -1 if score < 0 else 0
        return {
            "model_name": self.spec.name,
            "asset": context.asset,
            "decision_timeframe": self.trigger.decision_timeframe,
            "trigger_timeframe": self.trigger.trigger_timeframe,
            "timestamp": context.timestamp,
            "score": score,
            "direction_hint": direction,
            "conviction": min(abs(score), 1.0),
            "metadata": {"threshold": self.params["threshold"]},
        }


class DummyLegacyModel(BaseModel):
    meta = ModelMeta(
        name="legacy_direction",
        required_indicators=["EMA"],
        required_fields=["EMA.value"],
        hyperparameter_schema={"lookback": ParamDef(type="int", default=20, low=1, high=200)},
        min_history_bars=20,
    )

    def evaluate(self, features: FeatureVector) -> ModelOutput:
        return ModelOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            direction=1,
            conviction=0.75,
            metadata={"path": "legacy"},
        )

    def _batch_evaluate_impl(self, feature_df):
        raise NotImplementedError


class DummyLegacyScoringModel(ScoringModel):
    meta = ModelMeta(
        name="legacy_scoring",
        required_indicators=["RSI"],
        required_fields=["RSI.value"],
        hyperparameter_schema={"threshold": ParamDef(type="float", default=0.3, low=0.0, high=1.0)},
        min_history_bars=16,
        model_type="scoring",
    )

    def evaluate(self, features: FeatureVector) -> ScoringOutput:
        return ScoringOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            edge_score=-0.4,
            conviction=0.6,
            metadata={"path": "legacy_scoring"},
        )

    def _batch_evaluate_impl(self, feature_df):
        raise NotImplementedError


def _context(score: float = 0.5) -> ModelExecutionContext:
    return ModelExecutionContext(
        feature_vector=FeatureVector(
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1700000000.0,
            features={"score": score},
            bar_data={"close": 100_000.0},
        ),
        runtime_metadata={"origin": "test"},
        context_views={"regime": {"state": "risk_on"}},
    )


def test_strategy_model_v2_defaults_and_validation() -> None:
    model = DummyStrategyModel()
    assert model.params["threshold"] == 0.4
    assert model.validate_feature_coverage({"RSI"}) == ["ATR"]
    assert model.validate_required_fields({"RSI"}) == ["ATR.value"]
    assert model.validate_context_profiles({"vol"}) == ["regime"]


def test_strategy_model_v2_evaluate() -> None:
    model = DummyStrategyModel({"threshold": 0.8})
    decision: dict[str, Any] = model.evaluate(_context(0.7))
    assert decision["model_name"] == "dummy_v2"
    assert decision["score"] == 0.7
    assert decision["direction_hint"] == 1
    assert decision["metadata"]["threshold"] == 0.8


def test_legacy_base_model_adapter() -> None:
    adapter = LegacyBaseModelAdapter(
        DummyLegacyModel({}),
        trigger=ModelTriggerSpec(decision_timeframe="1h", base_timeframe="1m"),
    )
    decision = adapter.evaluate(_context())
    assert decision.model_name == "legacy_direction"
    assert decision.score == 0.75
    assert decision.direction_hint == 1
    assert decision.metadata["path"] == "legacy"


def test_legacy_scoring_model_adapter() -> None:
    adapter = LegacyScoringModelAdapter(
        DummyLegacyScoringModel({}),
        trigger=ModelTriggerSpec(decision_timeframe="4h", base_timeframe="1m"),
    )
    decision = adapter.evaluate(_context())
    assert decision.model_name == "legacy_scoring"
    assert decision.decision_timeframe == "4h"
    assert decision.score == -0.4
    assert decision.direction_hint == -1
    assert decision.metadata["path"] == "legacy_scoring"


def test_momentum_v2_wrapper() -> None:
    model = MomentumV2(
        {
            "rsi_long_threshold": 55,
            "rsi_short_threshold": 45,
            "require_macd_positive": False,
            "histogram_min_abs": 0.0,
        }
    )
    decision = model.evaluate(
        ModelExecutionContext(
            feature_vector=FeatureVector(
                asset="BTCUSDT",
                timeframe="1h",
                timestamp=1700000000.0,
                features={
                    "RSI": {"value": 60},
                    "MACD": {"histogram": 0.5, "line": 0.3},
                },
                bar_data={"close": 100_000.0},
            )
        )
    )
    assert decision.model_name == "MomentumV2"
    assert decision.score > 0
    assert decision.direction_hint == 1


def test_kyle_tfi_v2_wrapper() -> None:
    model = KyleTFIV2(
        {
            "tfi_z_long": 1.0,
            "tfi_z_short": -1.0,
            "atr_tp_mult": 2.0,
            "atr_sl_mult": 1.5,
        }
    )
    decision = model.evaluate(
        ModelExecutionContext(
            feature_vector=FeatureVector(
                asset="BTCUSDT",
                timeframe="1h",
                timestamp=1700000000.0,
                features={
                    "kyle_z": 1.5,
                    "kyle_regime": "informed",
                    "tfi_zscore": 1.2,
                    "ATR": 100.0,
                    "RSI": 55.0,
                },
                bar_data={"close": 100_000.0},
            )
        )
    )
    assert decision.model_name == "KyleTFIV2"
    assert decision.score > 0
    assert decision.direction_hint == 1
    assert "atr_tp" in decision.metadata


def test_vpin_kyle_v2_wrapper() -> None:
    model = VPINKyleV2(
        {
            "vpin_z_threshold": 1.0,
            "buy_ratio_long": 0.58,
            "buy_ratio_short": 0.42,
            "atr_tp_mult": 2.0,
            "atr_sl_mult": 1.5,
        }
    )
    decision = model.evaluate(
        ModelExecutionContext(
            feature_vector=FeatureVector(
                asset="BTCUSDT",
                timeframe="1h",
                timestamp=1700000000.0,
                features={
                    "vpin_z": 1.5,
                    "net_taker_buy_ratio": 0.61,
                    "kyle_z": 1.3,
                    "kyle_regime": "informed",
                    "ATR": 100.0,
                    "RSI": 55.0,
                },
                bar_data={"close": 100_000.0},
            )
        )
    )
    assert decision.model_name == "VPINKyleV2"
    assert decision.score > 0
    assert decision.direction_hint == 1
    assert "atr_sl" in decision.metadata


def test_mean_reversion_v2_wrapper() -> None:
    model = MeanReversionV2({})
    decision = model.evaluate(
        ModelExecutionContext(
            feature_vector=FeatureVector(
                asset="BTCUSDT",
                timeframe="1h",
                timestamp=1700000000.0,
                features={
                    "RSI": {"value": 25},
                    "BollingerBands": {"upper": 110, "lower": 95},
                    "ADX": {"adx": 15.0},
                    "KAMA_fast": 100.0,
                    "ATR": 2.0,
                },
                bar_data={"close": 90.0},
            )
        )
    )
    assert decision.model_name == "MeanReversionV2"
    assert decision.direction_hint == 1
    assert decision.score > 0


def test_price_action_v2_wrapper() -> None:
    model = PriceActionV2({})
    base_features = {"ATR": 2.0}
    bars = [
        {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
        {"open": 101.0, "high": 103.0, "low": 100.0, "close": 102.0},
        {"open": 102.0, "high": 104.0, "low": 101.0, "close": 103.0},
    ]
    decision = None
    for index, bar in enumerate(bars, start=1):
        decision = model.evaluate(
            ModelExecutionContext(
                feature_vector=FeatureVector(
                    asset="BTCUSDT",
                    timeframe="1h",
                    timestamp=1700000000.0 + index,
                    features=base_features,
                    bar_data=bar,
                )
            )
        )
    assert decision is not None
    assert decision.model_name == "PriceActionV2"
    assert decision.conviction >= 0.0
