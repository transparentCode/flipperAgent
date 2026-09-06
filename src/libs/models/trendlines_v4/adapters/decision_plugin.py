"""Thin Decision adapter for the dependency-free Trendlines V4 core."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from math import isfinite
from typing import Any

from apps.decision_app.domain.contracts import ResolvedModelBinding
from apps.decision_app.runtime.plugins import StateInitializationRequirement
from apps.decision_app.storage.state_codec import (
    decode_state_payload,
    encode_state_payload,
)
from libs.contracts.decision import (
    DecisionContext,
    ModelArtifact,
    ModelOutcome,
    ModelRequestContext,
    ModelSpec,
    StateReconstructionRequirement,
    WarmupRequirements,
    require_utc,
)
from libs.models.trendlines_v4.core import (
    HISTORY_CAPACITY_BARS,
    PIVOT_WINDOW,
    SideGeometry,
    TrendlineBar,
    TrendlineGeometry,
    TrendlineSnapshot,
    analyze_trendlines,
)

TRENDLINES_PLUGIN_NAME = "trendlines"
TRENDLINES_PLUGIN_VERSION = "1"
TRENDLINES_ARTIFACT_TYPE = "trendlines.geometry.v1"
TRENDLINES_STATE_SCHEMA_VERSION = "trendlines.state.v1"
_STATE_KEYS = frozenset(
    {"schema_version", "asset", "timeframe", "last_market_as_of", "bars"}
)

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
    state_reconstruction=StateReconstructionRequirement(
        durable_pit_required=True,
    ),
)


def _finite_positive_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not isfinite(result) or result <= 0:
        raise ValueError(f"{field_name} must be finite and positive")
    return result


def _validate_request_context(context: ModelRequestContext) -> None:
    if not isinstance(context, ModelRequestContext):
        raise TypeError("context must be a ModelRequestContext")
    if context.trigger_timeframe != context.decision_timeframe:
        raise ValueError("Trendlines requires matching trigger and decision timeframes")
    if context.trigger_mode != "on_bar_close":
        raise ValueError("Trendlines requires on_bar_close trigger mode")


def _validate_decision_context(context: DecisionContext) -> None:
    if not isinstance(context, DecisionContext):
        raise TypeError("context must be a DecisionContext")
    _validate_request_context(context)
    bar = context.decision_bar
    if bar is None:
        raise ValueError("Trendlines evaluation requires a decision bar")
    if not context.decision_bar_closed or not bar.closed:
        raise ValueError("Trendlines accepts closed decision bars only")
    if bar.timeframe != context.decision_timeframe:
        raise ValueError("decision bar timeframe must match decision timeframe")
    if bar.market_as_of != context.market_as_of:
        raise ValueError("decision bar cutoff must match context")
    if bar.bar_close_at != context.market_as_of:
        raise ValueError("closed decision bar must close at market_as_of")


def _decode_state(
    state_snapshot: object | None,
    context: ModelRequestContext,
) -> tuple[TrendlineBar, ...]:
    if state_snapshot is None:
        return ()
    if not isinstance(state_snapshot, str):
        raise TypeError("Trendlines state_snapshot must be an encoded state string")
    decoded = decode_state_payload(state_snapshot)
    if not isinstance(decoded, Mapping) or set(decoded) != _STATE_KEYS:
        raise ValueError("Trendlines state has an invalid schema")
    if decoded["schema_version"] != TRENDLINES_STATE_SCHEMA_VERSION:
        raise ValueError("Trendlines state schema_version is unsupported")
    if decoded["asset"] != context.asset:
        raise ValueError("Trendlines state asset does not match context")
    if decoded["timeframe"] != context.decision_timeframe:
        raise ValueError("Trendlines state timeframe does not match context")
    last_market_as_of = decoded["last_market_as_of"]
    if not isinstance(last_market_as_of, datetime):
        raise TypeError("Trendlines state last_market_as_of is invalid")
    require_utc(last_market_as_of, field_name="Trendlines state last_market_as_of")
    encoded_bars = decoded["bars"]
    if not isinstance(encoded_bars, tuple) or not encoded_bars:
        raise ValueError("Trendlines state bars must be a non-empty tuple")
    if len(encoded_bars) > HISTORY_CAPACITY_BARS:
        raise ValueError("Trendlines state exceeds the 300-bar capacity")
    bars: list[TrendlineBar] = []
    for index, encoded_bar in enumerate(encoded_bars):
        if not isinstance(encoded_bar, tuple) or len(encoded_bar) != 5:
            raise ValueError(f"Trendlines state bar {index} is invalid")
        closed_at, open_, high, low, close = encoded_bar
        if not isinstance(closed_at, datetime):
            raise TypeError(f"Trendlines state bar {index} timestamp is invalid")
        require_utc(closed_at, field_name=f"Trendlines state bar {index} timestamp")
        prices = (open_, high, low, close)
        if any(
            isinstance(value, bool)
            or not isinstance(value, float)
            or not isfinite(value)
            or value <= 0
            for value in prices
        ):
            raise ValueError(f"Trendlines state bar {index} prices are invalid")
        bar = TrendlineBar(closed_at, open_, high, low, close)
        if bars and bars[-1].closed_at >= bar.closed_at:
            raise ValueError("Trendlines state bars must be strictly increasing")
        bars.append(bar)
    if bars[-1].closed_at != last_market_as_of:
        raise ValueError("Trendlines state last cutoff must equal its final bar")
    return tuple(bars)


def _encode_state(context: DecisionContext, bars: Sequence[TrendlineBar]) -> str:
    return encode_state_payload(
        {
            "schema_version": TRENDLINES_STATE_SCHEMA_VERSION,
            "asset": context.asset,
            "timeframe": context.decision_timeframe,
            "last_market_as_of": context.market_as_of,
            "bars": tuple(
                (bar.closed_at, bar.open, bar.high, bar.low, bar.close) for bar in bars
            ),
        }
    )


def _line_value(line: TrendlineGeometry | None) -> Mapping[str, Any] | None:
    if line is None:
        return None
    return {
        "side": line.side,
        "start_anchor_at": line.start_anchor_at,
        "start_anchor_price": line.start_anchor_price,
        "end_anchor_at": line.end_anchor_at,
        "end_anchor_price": line.end_anchor_price,
        "slope_per_bar": line.slope_per_bar,
        "projected_price_at_market_as_of": line.projected_price_at_market_as_of,
        "post_anchor_body_crossed": line.post_anchor_body_crossed,
        "post_anchor_body_cross_count": line.post_anchor_body_cross_count,
        "projection_positive": line.projection_positive,
    }


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


def _to_trendline_bar(context: DecisionContext) -> TrendlineBar:
    bar = context.decision_bar
    if bar is None:
        raise ValueError("Trendlines evaluation requires a decision bar")
    return TrendlineBar(
        closed_at=context.market_as_of,
        open=_finite_positive_float(bar.open, field_name="open"),
        high=_finite_positive_float(bar.high, field_name="high"),
        low=_finite_positive_float(bar.low, field_name="low"),
        close=_finite_positive_float(bar.close, field_name="close"),
    )


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
                "pivot_window": snapshot.pivot_window,
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
