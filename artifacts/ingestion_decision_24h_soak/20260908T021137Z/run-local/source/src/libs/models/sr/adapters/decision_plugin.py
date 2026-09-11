"""Thin decision_app adapter for the deterministic SR model core."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from math import isfinite
from typing import Any

from libs.contracts.decision import (
    DataRequirement,
    DecisionContext,
    FeatureRequirement,
    ModelArtifact,
    ModelOutcome,
    ModelRequestContext,
    ModelSpec,
    StateReconstructionRequirement,
    WarmupRequirements,
)
from libs.models.sr.config import SRConfigResolver
from libs.models.sr.domain.bars import ClosedBar, SRStateKey
from libs.models.sr.domain.factory import create_initial_state
from libs.models.sr.domain.identity import deterministic_hash, utc_isoformat
from libs.models.sr.domain.snapshots import SRSnapshot
from libs.models.sr.domain.zones import ZoneStatus
from libs.models.sr.lifecycle.engine import SREngine
from libs.models.sr.serialization.state_codec import decode_state, encode_state

SR_PLUGIN_NAME = "sr"
SR_PLUGIN_VERSION = "1"
SR_ARTIFACT_TYPE = "sr.snapshot.v1"
SR_ATR_FEATURE_NAME = "ATR"
SR_ATR_FEATURE_VERSION = "1"


SR_MODEL_SPEC = ModelSpec(
    name=SR_PLUGIN_NAME,
    version=SR_PLUGIN_VERSION,
    stateful=True,
    output_kind="analytical",
    produces_artifact_type=SR_ARTIFACT_TYPE,
    supported_trigger_modes=("on_bar_close",),
    intrinsic_feature_requirements=(
        FeatureRequirement(name=SR_ATR_FEATURE_NAME, required=True),
    ),
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


def _canonical_bar_id(context: DecisionContext) -> str:
    bar = context.decision_bar
    if bar is None:
        raise ValueError("SR evaluation requires a decision bar")
    return deterministic_hash(
        {
            "adapter": "sr-decision-plugin",
            "asset": context.asset,
            "venue": context.venue,
            "instrument_id": context.instrument_id,
            "timeframe": context.decision_timeframe,
            "bar_open_at": utc_isoformat(bar.bar_open_at),
            "bar_close_at": utc_isoformat(bar.bar_close_at),
            "market_as_of": utc_isoformat(context.market_as_of),
            "open": str(bar.open),
            "high": str(bar.high),
            "low": str(bar.low),
            "close": str(bar.close),
            "volume": str(bar.volume),
            "taker_buy_base": (
                None if bar.taker_buy_base is None else str(bar.taker_buy_base)
            ),
        }
    )


def to_sr_closed_bar(context: DecisionContext, *, atr_at_close: object) -> ClosedBar:
    """Translate one validated closed decision bar at the SR float boundary."""

    if not isinstance(context, DecisionContext):
        raise TypeError("context must be a DecisionContext")
    bar = context.decision_bar
    if bar is None:
        raise ValueError("SR evaluation requires a decision bar")
    if not context.decision_bar_closed or not bar.closed:
        raise ValueError("SR adapter accepts closed decision bars only")
    if bar.market_as_of != context.market_as_of:
        raise ValueError("decision bar cutoff must match context")
    if bar.bar_close_at != context.market_as_of:
        raise ValueError("closed SR bar must close at market_as_of")
    state_key = SRStateKey(
        venue=context.venue,
        symbol=context.asset,
        timeframe=context.decision_timeframe,
    )
    return ClosedBar(
        state_key=state_key,
        bar_id=_canonical_bar_id(context),
        closed_at=context.market_as_of,
        open=_finite_positive_float(bar.open, field_name="open"),
        high=_finite_positive_float(bar.high, field_name="high"),
        low=_finite_positive_float(bar.low, field_name="low"),
        close=_finite_positive_float(bar.close, field_name="close"),
        atr_at_close=_finite_positive_float(
            atr_at_close,
            field_name="ATR feature value",
        ),
    )


def _zone_evidence(record: Any) -> Mapping[str, Any]:
    definition = record.definition
    runtime = record.runtime
    geometry = definition.geometry
    return {
        "zone_id": definition.zone_id,
        "side": definition.side.value,
        "center": geometry.center,
        "half_width": geometry.half_width,
        "lower_bound": geometry.lower_bound,
        "upper_bound": geometry.upper_bound,
        "source": definition.source,
        "created_at": utc_isoformat(definition.created_at),
        "available_at": utc_isoformat(definition.available_at),
        "atr_at_creation": definition.atr_at_creation,
        "status": runtime.status.value,
        "touch_count": runtime.touch_count,
        "fakeout_count": runtime.fakeout_count,
        "pending_breach_count": runtime.pending_breach_count,
        "age_bars": runtime.age_bars,
        "last_interaction_at": (
            None
            if runtime.last_interaction_at is None
            else utc_isoformat(runtime.last_interaction_at)
        ),
        "updated_at": utc_isoformat(runtime.updated_at),
    }


def _event_evidence(event: Any) -> Mapping[str, Any]:
    return {
        "event_id": event.event_id,
        "zone_id": event.zone_id,
        "event_type": event.event_type.value,
        "timestamp": utc_isoformat(event.timestamp),
        "price": event.price,
        "bar_id": event.bar_id,
    }


def _snapshot_value(
    snapshot: SRSnapshot,
    *,
    max_active_zones: int,
) -> Mapping[str, Any]:
    active_zones = tuple(
        record
        for record in snapshot.zones
        if record.runtime.status not in {ZoneStatus.BROKEN, ZoneStatus.EXPIRED}
    )
    terminal_zone_count = len(snapshot.zones) - len(active_zones)
    if len(active_zones) > max_active_zones:
        raise ValueError("SR active zone projection exceeds configured bound")
    return {
        "snapshot_id": snapshot.snapshot_id,
        "config_hash": snapshot.config_hash,
        "as_of": utc_isoformat(snapshot.as_of),
        "zone_count": len(snapshot.zones),
        "active_zone_count": len(active_zones),
        "terminal_zone_count": terminal_zone_count,
        "projected_zone_count": len(active_zones),
        "event_count": len(snapshot.events),
        "zones": tuple(_zone_evidence(record) for record in active_zones),
        "events": tuple(_event_evidence(event) for event in snapshot.events),
    }


class SRDecisionPlugin:
    """One SR core instance exposed through the D6 semantic plugin boundary."""

    spec = SR_MODEL_SPEC

    def __init__(self, parameters: Mapping[str, object]) -> None:
        if not isinstance(parameters, Mapping):
            raise TypeError("SR plugin parameters must be a mapping")
        raw_config = parameters.get("sr_config")
        if not isinstance(raw_config, Mapping):
            raise TypeError("SR plugin parameters require an sr_config mapping")
        self._config_resolver = SRConfigResolver(raw_config)

    def data_requests(
        self,
        base_context: ModelRequestContext,
        state_snapshot: object | None = None,
    ) -> Sequence[DataRequirement]:
        if not isinstance(base_context, ModelRequestContext):
            raise TypeError("base_context must be a ModelRequestContext")
        if state_snapshot is not None and not isinstance(state_snapshot, str):
            raise TypeError("SR state_snapshot must be an encoded state string")
        return ()

    def evaluate(
        self,
        context: DecisionContext,
        state_snapshot: object | None = None,
    ) -> ModelOutcome:
        if not isinstance(context, DecisionContext):
            raise TypeError("context must be a DecisionContext")
        resolved_config = self._config_resolver.resolve(
            asset=context.asset,
            timeframe=context.decision_timeframe,
        )
        state_key = SRStateKey(
            venue=context.venue,
            symbol=context.asset,
            timeframe=context.decision_timeframe,
        )
        previous_state = self._decode_state(state_snapshot, state_key, resolved_config)
        atr_snapshot = context.shared_features.get(SR_ATR_FEATURE_NAME)
        if atr_snapshot is None:
            raise ValueError("SR requires the ATR feature")
        if atr_snapshot.version != SR_ATR_FEATURE_VERSION:
            raise ValueError("SR ATR feature version is unsupported")
        atr_at_close = _finite_positive_float(
            atr_snapshot.value,
            field_name="ATR feature value",
        )
        closed_bar = to_sr_closed_bar(context, atr_at_close=atr_at_close)
        next_state, snapshot, _events = SREngine().step(
            previous_state,
            closed_bar,
            resolved_config,
        )
        artifact = ModelArtifact(
            binding_id=context.binding_id,
            lane_id=context.lane_id,
            asset=context.asset,
            decision_timeframe=context.decision_timeframe,
            trigger_timeframe=context.trigger_timeframe,
            market_as_of=context.market_as_of,
            artifact_type=SR_ARTIFACT_TYPE,
            value=_snapshot_value(
                snapshot,
                max_active_zones=resolved_config.runtime.max_active_zones,
            ),
            metadata={
                "snapshot_id": snapshot.snapshot_id,
                "zone_count": len(snapshot.zones),
                "event_count": len(snapshot.events),
            },
            provenance={
                "adapter": f"{SR_PLUGIN_NAME}@{SR_PLUGIN_VERSION}",
                "sr_config_hash": resolved_config.resolved_config_hash,
                "snapshot_id": snapshot.snapshot_id,
            },
        )
        return ModelOutcome(
            artifact=artifact,
            decision=None,
            proposed_next_state=encode_state(next_state),
        )

    def _decode_state(
        self,
        state_snapshot: object | None,
        state_key: SRStateKey,
        resolved_config: Any,
    ) -> Any:
        if state_snapshot is None:
            return create_initial_state(state_key, resolved_config)
        if not isinstance(state_snapshot, str):
            raise TypeError("SR state_snapshot must be an encoded state string")
        state = decode_state(state_snapshot)
        if state.state_key != state_key:
            raise ValueError("encoded SR state identity does not match context")
        if state.config_hash != resolved_config.resolved_config_hash:
            raise ValueError("encoded SR state config does not match binding config")
        return state


__all__ = [
    "SR_ARTIFACT_TYPE",
    "SR_MODEL_SPEC",
    "SR_PLUGIN_NAME",
    "SR_PLUGIN_VERSION",
    "SRDecisionPlugin",
    "to_sr_closed_bar",
]
