"""Canonical V2 strategy wrapper for Kyle-TFI directional logic."""

from __future__ import annotations

from libs.contracts.strategy_model import (
    ModelDecision,
    ModelExecutionContext,
    ModelInputContract,
    ModelTriggerSpec,
    StrategyModelSpec,
)
from libs.models.kyle_tfi.model import KyleTFIModel
from libs.models.strategy_model_v2 import StrategyModelV2
from libs.models.strategy_registry import StrategyModelRegistry


@StrategyModelRegistry.register("KyleTFIV2")
class KyleTFIV2(StrategyModelV2):
    spec = StrategyModelSpec(
        name="KyleTFIV2",
        version="v2",
        private_feature_engineering=False,
        description="Canonical V2 wrapper around Kyle-TFI directional logic.",
        tags=["kyle_tfi", "direction", "v2"],
    )
    trigger = ModelTriggerSpec(decision_timeframe="1h", base_timeframe="1m")
    inputs = ModelInputContract(
        required_indicators=list(KyleTFIModel.meta.required_indicators),
        required_fields=list(KyleTFIModel.meta.required_fields),
        external_data_sources=list(KyleTFIModel.meta.external_data_sources),
        warmup_bars=int(KyleTFIModel.meta.min_history_bars),
    )
    param_schema = dict(KyleTFIModel.meta.hyperparameter_schema)

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params or {})
        self._model = KyleTFIModel(self.params)

    def evaluate(self, context: ModelExecutionContext) -> ModelDecision:
        output = self._model.evaluate(context.feature_vector)
        return ModelDecision(
            model_name=self.spec.name,
            asset=output.asset,
            decision_timeframe=self.trigger.decision_timeframe,
            trigger_timeframe=self.trigger.trigger_timeframe or self.trigger.decision_timeframe,
            timestamp=float(output.timestamp),
            score=float(output.direction) * float(output.conviction),
            direction_hint=int(output.direction),
            conviction=float(output.conviction),
            metadata=dict(output.metadata),
        )
