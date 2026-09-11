"""Temporary adapters that bridge legacy model types into the canonical interface."""

from __future__ import annotations

from libs.contracts.signal import ModelOutput, ScoringOutput
from libs.contracts.strategy_model import (
    ModelDecision,
    ModelExecutionContext,
    ModelInputContract,
    ModelTriggerSpec,
    StrategyModelSpec,
)
from libs.models.base import BaseModel
from libs.models.scoring_base import ScoringModel
from libs.models.strategy_model_v2 import StrategyModelV2


class LegacyBaseModelAdapter(StrategyModelV2):
    """Wrap a legacy direction model as a canonical scoring-first model."""

    def __init__(
        self,
        wrapped: BaseModel,
        *,
        trigger: ModelTriggerSpec,
        inputs: ModelInputContract | None = None,
    ) -> None:
        self.wrapped = wrapped
        self.spec = StrategyModelSpec(
            name=wrapped.meta.name,
            version="legacy-adapter",
            stateful=False,
            trainable=bool(getattr(wrapped.meta, "trainable", False)),
            private_feature_engineering=False,
            description=f"Adapter over legacy BaseModel {wrapped.meta.name}",
            tags=["legacy", "adapter"],
        )
        self.trigger = trigger
        self.inputs = inputs or ModelInputContract(
            required_indicators=list(getattr(wrapped.meta, "required_indicators", [])),
            required_fields=list(getattr(wrapped.meta, "required_fields", [])),
            external_data_sources=list(getattr(wrapped.meta, "external_data_sources", [])),
            warmup_bars=int(getattr(wrapped.meta, "min_history_bars", 0)),
        )
        super().__init__(wrapped.params)

    def evaluate(self, context: ModelExecutionContext) -> ModelDecision:
        output = self.wrapped.evaluate(context.feature_vector)
        return _model_output_to_decision(output, self.trigger)


class LegacyScoringModelAdapter(StrategyModelV2):
    """Wrap a legacy scoring model as a canonical scoring-first model."""

    def __init__(
        self,
        wrapped: ScoringModel,
        *,
        trigger: ModelTriggerSpec,
        inputs: ModelInputContract | None = None,
    ) -> None:
        self.wrapped = wrapped
        self.spec = StrategyModelSpec(
            name=wrapped.meta.name,
            version="legacy-adapter",
            stateful=False,
            trainable=bool(getattr(wrapped.meta, "trainable", False)),
            private_feature_engineering=False,
            description=f"Adapter over legacy ScoringModel {wrapped.meta.name}",
            tags=["legacy", "adapter"],
        )
        self.trigger = trigger
        self.inputs = inputs or ModelInputContract(
            required_indicators=list(getattr(wrapped.meta, "required_indicators", [])),
            required_fields=list(getattr(wrapped.meta, "required_fields", [])),
            external_data_sources=list(getattr(wrapped.meta, "external_data_sources", [])),
            warmup_bars=int(getattr(wrapped.meta, "min_history_bars", 0)),
        )
        super().__init__(wrapped.params)

    def evaluate(self, context: ModelExecutionContext) -> ModelDecision:
        output = self.wrapped.evaluate(context.feature_vector)
        return _scoring_output_to_decision(output, self.trigger)


def _model_output_to_decision(
    output: ModelOutput,
    trigger: ModelTriggerSpec,
) -> ModelDecision:
    return ModelDecision(
        model_name=output.model_name,
        asset=output.asset,
        decision_timeframe=trigger.decision_timeframe,
        trigger_timeframe=trigger.trigger_timeframe or trigger.decision_timeframe,
        timestamp=float(output.timestamp),
        score=float(output.direction) * float(output.conviction),
        direction_hint=int(output.direction),
        conviction=float(output.conviction),
        metadata=dict(output.metadata),
    )


def _scoring_output_to_decision(
    output: ScoringOutput,
    trigger: ModelTriggerSpec,
) -> ModelDecision:
    score = float(output.edge_score)
    direction_hint = 1 if score > 0 else -1 if score < 0 else 0
    return ModelDecision(
        model_name=output.model_name,
        asset=output.asset,
        decision_timeframe=trigger.decision_timeframe,
        trigger_timeframe=trigger.trigger_timeframe or trigger.decision_timeframe,
        timestamp=float(output.timestamp),
        score=score,
        direction_hint=direction_hint,
        conviction=float(output.conviction),
        metadata=dict(output.metadata),
    )


__all__ = [
    "LegacyBaseModelAdapter",
    "LegacyScoringModelAdapter",
]
