"""Deterministic chart payload construction from approved evidence."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from libs.models.sr.domain import ContractValidationError, SREventType
from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.domain.identity import deterministic_hash, utc_isoformat
from libs.models.sr.evaluation import (
    ObservedEvent,
    SREvaluationTrace,
    ZoneObservation,
)
from libs.models.sr.evaluation.diagnostics import SRDiagnostics
from libs.models.sr.research.source.contracts import SourceBar
from libs.models.sr.research.viewer.casebook_payload import build_casebook_chart_payload

from libs.models.sr.research.studies.baseline_trial.contracts import (
    ResolvedInputConfig,
    TrialSpec,
)


SR_ZONE_VIEWER_PAYLOAD_SCHEMA_VERSION = "1.0"


def _timestamp(value) -> str:
    return utc_isoformat(value)


def _event_payload(event: ObservedEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "snapshot_id": event.snapshot_id,
        "snapshot_as_of": _timestamp(event.snapshot_as_of),
        "zone_id": event.zone_id,
        "event_type": event.event_type.value,
        "timestamp": _timestamp(event.timestamp),
        "time": int(event.timestamp.timestamp()),
        "price": event.price,
        "bar_id": event.bar_id,
    }


def _observation_payload(observation: ZoneObservation) -> dict[str, Any]:
    return {
        "zone_id": observation.zone_id,
        "side": observation.side.value,
        "source": observation.source,
        "atr_at_creation": observation.atr_at_creation,
        "render_kind": observation.render_kind.value,
        "lower_bound": observation.lower_bound,
        "center": observation.center,
        "upper_bound": observation.upper_bound,
        "created_at": _timestamp(observation.created_at),
        "available_at": _timestamp(observation.available_at),
        "visible_from": _timestamp(observation.visible_from),
        "visible_until": (
            None if observation.visible_until is None else _timestamp(observation.visible_until)
        ),
        "status": observation.status.value,
        "touch_count": observation.touch_count,
        "fakeout_count": observation.fakeout_count,
        "pending_breach_count": observation.pending_breach_count,
        "age_bars": observation.age_bars,
    }


def _zone_payload(
    observations: tuple[ZoneObservation, ...],
    diagnostic,
) -> dict[str, Any]:
    first = observations[0]
    immutable_fields = (
        "side",
        "source",
        "atr_at_creation",
        "render_kind",
        "lower_bound",
        "center",
        "upper_bound",
        "created_at",
        "available_at",
        "visible_from",
    )
    for observation in observations[1:]:
        for field_name in immutable_fields:
            if getattr(observation, field_name) != getattr(first, field_name):
                raise ContractValidationError(
                    f"zone definition field changed: {field_name}"
                )
    visible_until_values = [
        observation.visible_until
        for observation in observations
        if observation.visible_until is not None
    ]
    if visible_until_values and any(value != visible_until_values[0] for value in visible_until_values):
        raise ContractValidationError("zone visible_until changed across observations")
    if diagnostic.zone_id != first.zone_id:
        raise ContractValidationError("zone diagnostic identity does not match observation")
    if diagnostic.terminal_at != (
        None if not visible_until_values else visible_until_values[0]
    ):
        raise ContractValidationError("zone terminal visibility does not match diagnostics")
    if diagnostic.final_status is not observations[-1].status:
        raise ContractValidationError("zone final status does not match diagnostics")
    return {
        "zone_id": first.zone_id,
        "side": first.side.value,
        "source": first.source,
        "atr_at_creation": first.atr_at_creation,
        "render_kind": first.render_kind.value,
        "lower_bound": first.lower_bound,
        "center": first.center,
        "upper_bound": first.upper_bound,
        "created_at": _timestamp(first.created_at),
        "available_at": _timestamp(first.available_at),
        "visible_from": _timestamp(first.visible_from),
        "visible_until": (
            None
            if not visible_until_values
            else _timestamp(visible_until_values[0])
        ),
        "final_status": diagnostic.final_status.value,
        "lifetime_bars": diagnostic.lifetime_bars,
        "touch_count": diagnostic.touch_count,
        "fakeout_count": diagnostic.fakeout_count,
        "pending_breach_count": observations[-1].pending_breach_count,
        "age_bars": observations[-1].age_bars,
        "left_censored": diagnostic.left_censored,
        "right_censored": diagnostic.right_censored,
    }


def build_chart_payload(
    *,
    trial: TrialSpec,
    bundle_id: str | None,
    resolved_sr_config,
    resolved_input: ResolvedInputConfig,
    source_bars: tuple[SourceBar, ...],
    trace: SREvaluationTrace,
    diagnostics: SRDiagnostics,
) -> dict[str, Any]:
    """Build one JSON-safe payload; no model or provider calls occur here."""
    if (
        type(trial) is not TrialSpec
        or type(resolved_sr_config) is not ResolvedSRConfig
        or type(resolved_input) is not ResolvedInputConfig
        or type(trace) is not SREvaluationTrace
        or type(diagnostics) is not SRDiagnostics
    ):
        raise ContractValidationError("chart payload inputs have invalid contract types")
    if type(source_bars) is not tuple or not source_bars or any(
        type(bar) is not SourceBar for bar in source_bars
    ):
        raise ContractValidationError("source_bars must be a non-empty SourceBar tuple")
    if (
        resolved_sr_config.asset != trial.symbol
        or resolved_sr_config.timeframe != trial.timeframe
        or resolved_input.asset != trial.symbol
        or resolved_input.timeframe != trial.timeframe
        or trace.config_hash != resolved_sr_config.resolved_config_hash
        or diagnostics.trace_id != trace.trace_id
    ):
        raise ContractValidationError("chart payload identities do not reconcile")
    observations_by_zone: OrderedDict[str, list[ZoneObservation]] = OrderedDict()
    first_positions: dict[str, int] = {}
    for position, observation in enumerate(trace.zone_observations):
        observations_by_zone.setdefault(observation.zone_id, []).append(observation)
        first_positions.setdefault(observation.zone_id, position)
    diagnostics_by_zone = {zone.zone_id: zone for zone in diagnostics.zones}
    if set(observations_by_zone) != set(diagnostics_by_zone):
        raise ContractValidationError(
            "chart payload zone observations and diagnostics must reconcile"
        )
    ordered_zone_ids = sorted(
        observations_by_zone,
        key=lambda zone_id: (first_positions[zone_id], zone_id),
    )
    zones = tuple(
        _zone_payload(
            tuple(observations_by_zone[zone_id]),
            diagnostics_by_zone[zone_id],
        )
        for zone_id in ordered_zone_ids
    )
    candles = tuple(
        {
            "time": int(bar.open_time.timestamp()),
            "open_time": _timestamp(bar.open_time),
            "closed_at": _timestamp(bar.closed_at),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "bar_id": bar.bar_id,
        }
        for bar in source_bars
    )
    return {
        "schema_version": SR_ZONE_VIEWER_PAYLOAD_SCHEMA_VERSION,
        "trial_name": trial.trial_name,
        "bundle_id": bundle_id,
        "sr_config_hash": resolved_sr_config.resolved_config_hash,
        "sr_field_provenance": [list(pair) for pair in resolved_sr_config.field_provenance],
        "input_hash": resolved_input.resolved_input_hash,
        "input_field_provenance": [list(pair) for pair in resolved_input.field_provenance],
        "trace_id": trace.trace_id,
        "diagnostics_id": diagnostics.diagnostics_id,
        "viewer": trial.viewer.to_payload(),
        "candles": list(candles),
        "zones": list(zones),
        "events": [_event_payload(event) for event in trace.events],
        "event_types": [event_type.value for event_type in SREventType],
    }


def chart_payload_identity(payload: dict[str, Any]) -> str:
    """Hash chart semantics without circular bundle-id binding."""
    identity = dict(payload)
    identity.pop("bundle_id", None)
    return deterministic_hash(identity)


__all__ = [
    "SR_ZONE_VIEWER_PAYLOAD_SCHEMA_VERSION",
    "build_casebook_chart_payload",
    "build_chart_payload",
    "chart_payload_identity",
]
