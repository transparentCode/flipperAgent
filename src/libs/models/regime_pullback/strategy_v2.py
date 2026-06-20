"""Canonical V2 strategy wrapper for regime-pullback scoring logic."""

from __future__ import annotations

from libs.contracts.strategy_model import (
    ModelDecision,
    ModelExecutionContext,
    ModelInputContract,
    ModelTriggerSpec,
    StrategyModelSpec,
)
from libs.models.regime_pullback.model import RegimePullbackScorer
from libs.models.strategy_model_v2 import StrategyModelV2
from libs.models.strategy_registry import StrategyModelRegistry


@StrategyModelRegistry.register("RegimePullbackV2")
class RegimePullbackV2(StrategyModelV2):
    spec = StrategyModelSpec(
        name="RegimePullbackV2",
        version="v2",
        private_feature_engineering=False,
        description="Canonical V2 wrapper around regime-pullback scoring logic.",
        tags=["regime_pullback", "scoring", "v2"],
    )
    trigger = ModelTriggerSpec(decision_timeframe="1h", base_timeframe="1m")
    inputs = ModelInputContract(
        required_indicators=list(RegimePullbackScorer.meta.required_indicators),
        required_fields=list(RegimePullbackScorer.meta.required_fields),
        external_data_sources=list(RegimePullbackScorer.meta.external_data_sources),
        warmup_bars=int(RegimePullbackScorer.meta.min_history_bars),
    )
    param_schema = dict(RegimePullbackScorer.meta.hyperparameter_schema)

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params or {})
        self._scorer = RegimePullbackScorer(self.params)

    def evaluate(self, context: ModelExecutionContext) -> ModelDecision:
        output = self._scorer.evaluate(context.feature_vector)
        score = float(output.edge_score)
        direction_hint = 1 if score > 0 else -1 if score < 0 else 0
        return ModelDecision(
            model_name=self.spec.name,
            asset=output.asset,
            decision_timeframe=self.trigger.decision_timeframe,
            trigger_timeframe=self.trigger.trigger_timeframe or self.trigger.decision_timeframe,
            timestamp=float(output.timestamp),
            score=score,
            direction_hint=direction_hint,
            conviction=float(output.conviction),
            metadata=dict(output.metadata),
        )
