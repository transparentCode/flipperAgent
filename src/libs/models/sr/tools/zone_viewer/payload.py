"""Deterministic chart payload construction from approved evidence."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError, SREventType
from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.domain.identity import deterministic_hash, utc_isoformat
from libs.models.sr.evaluation.contracts import (
    ObservedEvent,
    SREvaluationTrace,
    ZoneObservation,
)
from libs.models.sr.evaluation.diagnostics import SRDiagnostics
from libs.models.sr.research.source.contracts import SourceBar

from libs.models.sr.scripts.baseline_trial.contracts import (
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


def _casebook_zone(case: dict[str, Any]) -> dict[str, Any]:
    zone = case.get("zone")
    if type(zone) is not dict:
        raise ContractValidationError("casebook case zone must be a mapping")
    required = {
        "zone_id", "side", "source", "render_kind", "lower_bound", "center",
        "upper_bound", "atr_at_creation", "created_at", "available_at",
        "visible_from", "visible_until", "age_bars_at_touch", "touch_count_at_touch",
        "fakeout_count_at_touch", "pending_breach_count_at_touch",
    }
    if set(zone) != required:
        raise ContractValidationError("casebook zone schema mismatch")
    return {
        "zone_id": zone["zone_id"],
        "side": zone["side"],
        "source": zone["source"],
        "atr_at_creation": zone["atr_at_creation"],
        "render_kind": zone["render_kind"],
        "lower_bound": zone["lower_bound"],
        "center": zone["center"],
        "upper_bound": zone["upper_bound"],
        "created_at": zone["created_at"],
        "available_at": zone["available_at"],
        "visible_from": zone["visible_from"],
        "visible_until": zone["visible_until"],
        "final_status": case["status_after_horizon"],
        "lifetime_bars": zone["age_bars_at_touch"],
        "touch_count": zone["touch_count_at_touch"],
        "fakeout_count": zone["fakeout_count_at_touch"],
        "pending_breach_count": zone["pending_breach_count_at_touch"],
        "age_bars": zone["age_bars_at_touch"],
        "left_censored": False,
        "right_censored": case["pooled_outcome"]["right_censored"],
    }


def _casebook_event(event: dict[str, Any], case_id: str) -> dict[str, Any]:
    if type(event) is not dict:
        raise ContractValidationError("casebook event must be a mapping")
    required = {"event_id", "snapshot_id", "snapshot_as_of", "zone_id", "event_type", "timestamp", "time", "price", "bar_id"}
    if set(event) != required:
        raise ContractValidationError("casebook event schema mismatch")
    return {**event, "case_id": case_id}


def build_casebook_chart_payload(
    *,
    trial_name: str,
    bundle_id: str | None,
    viewer: dict[str, Any],
    source_bars: tuple[SourceBar, ...],
    audit: dict[str, Any],
    sr_config_hash: str | None = None,
    input_hash: str | None = None,
) -> dict[str, Any]:
    """Build the additive V1.10 casebook payload from an immutable audit ledger."""
    if type(trial_name) is not str or not trial_name.strip():
        raise ContractValidationError("casebook trial_name must be a non-empty string")
    if type(bundle_id) not in (str, type(None)):
        raise ContractValidationError("casebook bundle_id must be a string or None")
    if type(viewer) is not dict or not viewer:
        raise ContractValidationError("casebook viewer must be a non-empty mapping")
    if type(source_bars) is not tuple or len(source_bars) != 629 or any(type(bar) is not SourceBar for bar in source_bars):
        raise ContractValidationError("casebook source bars must contain exactly 629 SourceBar values")
    if type(audit) is not dict or audit.get("case_count") != 36 or type(audit.get("cases")) is not list or len(audit["cases"]) != 36:
        raise ContractValidationError("casebook audit must contain exactly 36 cases")
    cases = tuple(audit["cases"])
    required_case = {
        "schema_version", "case_id", "record_id", "comparison_real_outcome_id", "zone_id", "side", "fold",
        "touch_bar_id", "first_touch_at", "zone", "touch_bar", "entering_status",
        "after_touch_status", "pooled_outcome", "fold_local_outcome", "comparison",
        "creation_event", "lifecycle_events", "horizon_lifecycle_class", "status_after_horizon",
    }
    if any(type(case) is not dict or set(case) != required_case for case in cases):
        raise ContractValidationError("casebook case schema mismatch")
    candles = [
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
    ]
    case_payloads: list[dict[str, Any]] = []
    zones: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for case in cases:
        pooled = case["pooled_outcome"]
        if type(pooled) is not dict or pooled.get("tenth_outcome_bar_closed_at") is None:
            raise ContractValidationError("casebook pooled outcome must provide the tenth-bar horizon")
        horizon = pooled["tenth_outcome_bar_closed_at"]
        outcome_window = {
            "start": _timestamp(datetime.fromisoformat(case["first_touch_at"].replace("Z", "+00:00")) + timedelta(days=1)),
            "end": horizon,
            "offset_bars": 1,
            "horizon_bars": 10,
            "policy": "half_open_utc_daily",
        }
        zone = _casebook_zone(case)
        selected_events = [_casebook_event(case["creation_event"], case["case_id"])]
        selected_events.extend(_casebook_event(event, case["case_id"]) for event in case["lifecycle_events"])
        case_payload = {
            "case_id": case["case_id"],
            "record_id": case["record_id"],
            "comparison_real_outcome_id": case["comparison_real_outcome_id"],
            "zone_id": case["zone_id"],
            "side": case["side"],
            "fold": case["fold"],
            "touch_bar_id": case["touch_bar_id"],
            "first_touch_at": case["first_touch_at"],
            "close_location": case["touch_bar"]["close_location"],
            "horizon_lifecycle_class": case["horizon_lifecycle_class"],
            "status_after_horizon": case["status_after_horizon"],
            "zone": zone,
            "touch_bar": case["touch_bar"],
            "pooled_outcome": pooled,
            "fold_local_outcome": case["fold_local_outcome"],
            "comparison": case["comparison"],
            "creation_event": selected_events[0],
            "lifecycle_events": selected_events[1:],
            "events": selected_events,
            "outcome_window": outcome_window,
        }
        case_payloads.append(case_payload)
        zones.append(zone)
        events.extend(selected_events)
    selected_case_id = case_payloads[0]["case_id"]
    return {
        "schema_version": SR_ZONE_VIEWER_PAYLOAD_SCHEMA_VERSION,
        "trial_name": trial_name,
        "bundle_id": bundle_id,
        "audit_id": audit.get("audit_id"),
        "trace_id": audit.get("trace_id"),
        "sr_config_hash": sr_config_hash,
        "input_hash": input_hash,
        "viewer": viewer,
        "candles": candles,
        "zones": zones,
        "events": events,
        "event_types": [event_type.value for event_type in SREventType],
        "casebook": {
            "schema_version": SR_ZONE_VIEWER_PAYLOAD_SCHEMA_VERSION,
            "case_order": ["first_touch_at", "zone_id"],
            "selected_case_id": selected_case_id,
            "cases": case_payloads,
            "case_count": len(case_payloads),
            "disposition": audit.get("v19_disposition"),
            "notice": "Diagnostic-only context audit; V1.9 negative disposition is unchanged.",
        },
    }


__all__ = [
    "SR_ZONE_VIEWER_PAYLOAD_SCHEMA_VERSION",
    "build_casebook_chart_payload",
    "build_chart_payload",
    "chart_payload_identity",
]
