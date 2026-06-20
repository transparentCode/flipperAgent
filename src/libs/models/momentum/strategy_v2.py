"""Canonical V2 strategy wrapper for momentum directional logic."""

from __future__ import annotations

from libs.contracts.strategy_model import (
    ModelDecision,
    ModelExecutionContext,
    ModelInputContract,
    ModelTriggerSpec,
    StrategyModelSpec,
)
from libs.models.momentum.model import MomentumModel
from libs.models.strategy_model_v2 import StrategyModelV2
from libs.models.strategy_registry import StrategyModelRegistry


@StrategyModelRegistry.register("MomentumV2")
class MomentumV2(StrategyModelV2):
    spec = StrategyModelSpec(
        name="MomentumV2",
        version="v2",
        private_feature_engineering=False,
        description="Canonical V2 wrapper around momentum directional logic.",
        tags=["momentum", "direction", "v2"],
    )
    trigger = ModelTriggerSpec(decision_timeframe="1h", base_timeframe="1m")
    inputs = ModelInputContract(
        required_indicators=list(MomentumModel.meta.required_indicators),
        required_fields=list(MomentumModel.meta.required_fields),
        external_data_sources=list(MomentumModel.meta.external_data_sources),
        warmup_bars=int(MomentumModel.meta.min_history_bars),
    )
    param_schema = dict(MomentumModel.meta.hyperparameter_schema)

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params or {})
        self._model = MomentumModel(self.params)

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
