"""Deterministic V1.10 casebook payload construction from immutable evidence."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from libs.models.sr.domain import ContractValidationError, SREventType
from libs.models.sr.domain.identity import utc_isoformat
from libs.models.sr.research.source.contracts import SourceBar


SR_ZONE_VIEWER_PAYLOAD_SCHEMA_VERSION = "1.0"


def _timestamp(value) -> str:
    return utc_isoformat(value)


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


__all__ = ["SR_ZONE_VIEWER_PAYLOAD_SCHEMA_VERSION", "build_casebook_chart_payload"]
