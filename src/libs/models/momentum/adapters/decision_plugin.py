"""Thin structural DecisionModelPlugin adapter for Momentum."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar

from libs.contracts.decision import (
    CausalBarView,
    DataRequirement,
    DecisionContext,
    FeatureRequirement,
    FeatureSnapshot,
    ModelArtifact,
    ModelDecision,
    ModelOutcome,
    ModelRequestContext,
    ModelSpec,
    ModelState,
)
from libs.models.momentum.config import MomentumConfig
from libs.models.momentum.core import (
    MomentumObservation,
    coerce_numeric_evidence,
    evaluate_momentum,
)

MOMENTUM_MODEL_SPEC = ModelSpec(
    name="momentum",
    version="1",
    stateful=False,
    output_kind="decision_capable",
    produces_artifact_type="momentum.signal.v1",
    supported_trigger_modes=("on_bar_close",),
    intrinsic_feature_requirements=(
        FeatureRequirement(name="RSI"),
        FeatureRequirement(name="MACD"),
    ),
)


def _feature_number(value: object, *, field_name: str) -> float:
    return coerce_numeric_evidence(value, field_name=field_name)


def _require_feature(
    context: DecisionContext,
    *,
    name: str,
) -> FeatureSnapshot:
    snapshot = context.shared_features.get(name)
    if snapshot is None:
        raise ValueError(f"required shared feature {name!r} is missing")
    if snapshot.version != "1":
        raise ValueError(f"shared feature {name!r} must use version 1")
    if snapshot.market_as_of != context.market_as_of:
        raise ValueError(
            f"shared feature {name!r} cutoff must match context market_as_of"
        )
    return snapshot


def _observation_from_context(context: DecisionContext) -> MomentumObservation:
    rsi_snapshot = _require_feature(context, name="RSI")
    macd_snapshot = _require_feature(context, name="MACD")

    rsi = _feature_number(rsi_snapshot.value, field_name="RSI value")
    if not 0.0 <= rsi <= 100.0:
        raise ValueError("RSI value must be between 0 and 100")

    if not isinstance(macd_snapshot.value, Mapping):
        raise TypeError("MACD value must be a mapping")
    if "histogram" not in macd_snapshot.value:
        raise ValueError("MACD value must contain histogram")
    if "line" not in macd_snapshot.value:
        raise ValueError("MACD value must contain line")

    return MomentumObservation(
        rsi=rsi,
        macd_histogram=_feature_number(
            macd_snapshot.value["histogram"],
            field_name="MACD histogram",
        ),
        macd_line=_feature_number(
            macd_snapshot.value["line"],
            field_name="MACD line",
        ),
    )


@dataclass(frozen=True, slots=True, init=False)
class MomentumDecisionPlugin:
    """Stateless adapter from DecisionContext to the Momentum semantic core."""

    spec: ClassVar[ModelSpec] = MOMENTUM_MODEL_SPEC
    config: MomentumConfig = field(init=False)

    def __init__(
        self, config: MomentumConfig | Mapping[str, Any] | None = None
    ) -> None:
        if config is None:
            resolved_config = MomentumConfig()
        elif isinstance(config, MomentumConfig):
            resolved_config = config
        else:
            resolved_config = MomentumConfig.from_mapping(config)
        object.__setattr__(self, "config", resolved_config)

    def data_requests(
        self,
        base_context: ModelRequestContext,
        state_snapshot: ModelState = None,
    ) -> Sequence[DataRequirement]:
        if not isinstance(base_context, ModelRequestContext):
            raise TypeError("base_context must be a ModelRequestContext")
        if state_snapshot is not None:
            raise ValueError("MomentumDecisionPlugin is stateless")
        return ()

    def evaluate(
        self,
        context: DecisionContext,
        state_snapshot: ModelState = None,
    ) -> ModelOutcome:
        if not isinstance(context, DecisionContext):
            raise TypeError("context must be a DecisionContext")
        if state_snapshot is not None:
            raise ValueError("MomentumDecisionPlugin is stateless")
        if context.decision_bar is None or not context.decision_bar_closed:
            raise ValueError("Momentum requires a closed decision bar")
        if not isinstance(context.decision_bar, CausalBarView):
            raise TypeError("decision_bar must be a CausalBarView")

        observation = _observation_from_context(context)
        result = evaluate_momentum(observation, self.config)
        evidence = {
            "rsi": observation.rsi,
            "macd_histogram": observation.macd_histogram,
            "macd_line": observation.macd_line,
        }
        artifact = ModelArtifact(
            binding_id=context.binding_id,
            lane_id=context.lane_id,
            asset=context.asset,
            decision_timeframe=context.decision_timeframe,
            trigger_timeframe=context.trigger_timeframe,
            market_as_of=context.market_as_of,
            artifact_type=self.spec.produces_artifact_type,
            value={
                "direction": result.direction,
                "conviction": result.conviction,
                "score": result.score,
            },
            metadata=evidence,
            provenance={"plugin": self.spec.name, "version": self.spec.version},
        )
        decision = None
        if result.direction != 0:
            decision = ModelDecision(
                binding_id=context.binding_id,
                asset=context.asset,
                decision_timeframe=context.decision_timeframe,
                trigger_timeframe=context.trigger_timeframe,
                market_as_of=context.market_as_of,
                signal_time=context.market_as_of,
                direction_hint=result.direction,
                score=result.score,
                conviction=result.conviction,
                metadata=evidence,
            )
        return ModelOutcome(
            artifact=artifact,
            decision=decision,
            metadata={"plugin": self.spec.name, "version": self.spec.version},
            proposed_next_state=None,
        )


__all__ = ["MOMENTUM_MODEL_SPEC", "MomentumDecisionPlugin"]
