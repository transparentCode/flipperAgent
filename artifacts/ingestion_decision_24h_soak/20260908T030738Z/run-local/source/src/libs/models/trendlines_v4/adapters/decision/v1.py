"""Decision compatibility view for geometry.v1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from apps.decision_app.domain.contracts import ResolvedModelBinding
from apps.decision_app.runtime.plugins import StateInitializationRequirement
from libs.contracts.decision import (
    DecisionContext,
    ModelArtifact,
    ModelOutcome,
    ModelRequestContext,
    ModelSpec,
    StateReconstructionRequirement,
    WarmupRequirements,
)
from libs.models.trendlines_v4.core import (
    HISTORY_CAPACITY_BARS,
    PIVOT_WINDOW,
    SideGeometry,
    TrendlineSnapshot,
    analyze_trendlines,
)

from .common import (
    TRENDLINES_STATE_SCHEMA_VERSION,
    _decode_state,
    _encode_state,
    _line_value,
    _to_trendline_bar,
    _validate_decision_context,
    _validate_request_context,
)

TRENDLINES_PLUGIN_NAME = "trendlines"
TRENDLINES_PLUGIN_VERSION = "1"
TRENDLINES_ARTIFACT_TYPE = "trendlines.geometry.v1"

TRENDLINES_MODEL_SPEC = ModelSpec(
    name=TRENDLINES_PLUGIN_NAME,
    version=TRENDLINES_PLUGIN_VERSION,
    stateful=True,
    output_kind="analytical",
    produces_artifact_type=TRENDLINES_ARTIFACT_TYPE,
    supported_trigger_modes=("on_bar_close",),
    intrinsic_feature_requirements=(),
    intrinsic_data_requirements=(),
    dependency_requirements=(),
    warmup_requirements=WarmupRequirements(),
    state_reconstruction=StateReconstructionRequirement(durable_pit_required=True),
)


def _side_value(side: SideGeometry) -> Mapping[str, Any]:
    return {
        "structural": _line_value(side.structural),
        "current_valid": _line_value(side.current_valid),
        "same_geometry": side.same_geometry,
    }


def _snapshot_value(snapshot: TrendlineSnapshot) -> Mapping[str, Any]:
    return {
        "schema_version": snapshot.schema_version,
        "history_bar_count": snapshot.history_bar_count,
        "history_capacity_bars": snapshot.history_capacity_bars,
        "pivot_window": snapshot.pivot_window,
        "history_start_at": snapshot.history_start_at,
        "market_as_of": snapshot.market_as_of,
        "support": _side_value(snapshot.support),
        "resistance": _side_value(snapshot.resistance),
    }


def trendlines_initialization_requirement(
    binding: ResolvedModelBinding,
) -> StateInitializationRequirement:
    """Return the exact bounded cold-rewarm requirement for Trendlines V4."""

    if not isinstance(binding, ResolvedModelBinding):
        raise TypeError("binding must be a ResolvedModelBinding")
    if (binding.plugin_name, binding.plugin_version) != (
        TRENDLINES_PLUGIN_NAME,
        TRENDLINES_PLUGIN_VERSION,
    ):
        raise ValueError("binding is not trendlines@1")
    if binding.trigger_timeframe != binding.decision_timeframe:
        raise ValueError("Trendlines requires matching trigger and decision timeframes")
    if binding.parameters:
        raise ValueError("Trendlines v1 does not accept binding parameters")
    return StateInitializationRequirement(trigger_steps=HISTORY_CAPACITY_BARS)


class TrendlinesV4DecisionPlugin:
    """One bounded stateful Decision adapter around the V4 geometry core."""

    spec = TRENDLINES_MODEL_SPEC

    def __init__(self, parameters: Mapping[str, object]) -> None:
        if not isinstance(parameters, Mapping):
            raise TypeError("Trendlines plugin parameters must be a mapping")
        if parameters:
            raise ValueError("Trendlines v1 does not accept binding parameters")

    def data_requests(
        self,
        base_context: ModelRequestContext,
        state_snapshot: object | None = None,
    ) -> Sequence[Any]:
        _validate_request_context(base_context)
        _decode_state(state_snapshot, base_context)
        return ()

    def evaluate(
        self,
        context: DecisionContext,
        state_snapshot: object | None = None,
    ) -> ModelOutcome:
        _validate_decision_context(context)
        previous_bars = _decode_state(state_snapshot, context)
        if previous_bars and previous_bars[-1].closed_at >= context.market_as_of:
            raise ValueError("Trendlines cutoff must advance strictly")
        current_bar = _to_trendline_bar(context)
        bars = (*previous_bars, current_bar)[-HISTORY_CAPACITY_BARS:]
        snapshot = analyze_trendlines(bars)
        artifact = ModelArtifact(
            binding_id=context.binding_id,
            lane_id=context.lane_id,
            asset=context.asset,
            decision_timeframe=context.decision_timeframe,
            trigger_timeframe=context.trigger_timeframe,
            market_as_of=context.market_as_of,
            artifact_type=TRENDLINES_ARTIFACT_TYPE,
            value=_snapshot_value(snapshot),
            metadata={
                "history_bar_count": snapshot.history_bar_count,
                "history_capacity_bars": snapshot.history_capacity_bars,
                "pivot_window": PIVOT_WINDOW,
            },
            provenance={
                "adapter": f"{TRENDLINES_PLUGIN_NAME}@{TRENDLINES_PLUGIN_VERSION}",
                "core_schema": snapshot.schema_version,
                "history_capacity_bars": HISTORY_CAPACITY_BARS,
                "pivot_window": PIVOT_WINDOW,
            },
        )
        return ModelOutcome(
            artifact=artifact,
            decision=None,
            proposed_next_state=_encode_state(context, bars),
        )


__all__ = [
    "TRENDLINES_ARTIFACT_TYPE",
    "TRENDLINES_MODEL_SPEC",
    "TRENDLINES_PLUGIN_NAME",
    "TRENDLINES_PLUGIN_VERSION",
    "TRENDLINES_STATE_SCHEMA_VERSION",
    "TrendlinesV4DecisionPlugin",
    "trendlines_initialization_requirement",
]
