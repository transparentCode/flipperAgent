"""Explicit canonical evidence serializers and atomic bundle publication."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from libs.models.sr.domain.identity import canonical_json, deterministic_hash, utc_isoformat

from libs.models.sr.research.studies.baseline_trial.contracts import (
    BundleMember,
    BundlePublication,
    EvidenceManifest,
    BASELINE_WINDOW_POLICY,
    SR_BASELINE_TRIAL_SCHEMA_VERSION,
    TrialResult,
    effective_provider_request_bounds,
)
from libs.models.sr.research.studies.baseline_trial.chart_payload import (
    build_chart_payload,
    chart_payload_identity,
)


_MEMBER_NAMES = (
    "source_bars.json",
    "model_bars.json",
    "trace.json",
    "diagnostics.json",
    "chart_payload.json",
)
_MISSING = object()


def _bytes(payload: dict[str, Any]) -> bytes:
    return canonical_json(payload).encode("utf-8") + b"\n"


def _file_hash(data: bytes) -> str:
    return sha256(data).hexdigest()


def _state_key_payload(state_key) -> dict[str, str]:
    return {
        "venue": state_key.venue,
        "symbol": state_key.symbol,
        "timeframe": state_key.timeframe,
    }


def _source_payload(result: TrialResult) -> dict[str, Any]:
    dataset = result.dataset
    return {
        "schema_version": SR_BASELINE_TRIAL_SCHEMA_VERSION,
        "trial_name": result.trial.trial_name,
        "requested_since": utc_isoformat(dataset.requested_since),
        "requested_until": utc_isoformat(dataset.requested_until),
        "actual_since": utc_isoformat(dataset.actual_since),
        "actual_until": utc_isoformat(dataset.actual_until),
        "raw_row_count": dataset.raw_row_count,
        "adapter_limit": dataset.adapter_limit,
        "gap_policy": dataset.gap_policy,
        "bars": [
            {
                "open_time": utc_isoformat(bar.open_time),
                "closed_at": utc_isoformat(bar.closed_at),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "bar_id": bar.bar_id,
            }
            for bar in dataset.bars
        ],
    }


def _model_payload(result: TrialResult) -> dict[str, Any]:
    return {
        "schema_version": SR_BASELINE_TRIAL_SCHEMA_VERSION,
        "state_key": _state_key_payload(result.model_bars[0].state_key),
        "atr": result.atr.to_payload(),
        "bars": [
            {
                "bar_id": bar.bar_id,
                "closed_at": utc_isoformat(bar.closed_at),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "atr_at_close": bar.atr_at_close,
            }
            for bar in result.model_bars
        ],
    }


def _zone_definition_payload(observation) -> dict[str, Any]:
    return {
        "zone_id": observation.zone_id,
        "side": observation.side.value,
        "source": observation.source,
        "atr_at_creation": observation.atr_at_creation,
        "render_kind": observation.render_kind.value,
        "lower_bound": observation.lower_bound,
        "center": observation.center,
        "upper_bound": observation.upper_bound,
        "created_at": utc_isoformat(observation.created_at),
        "available_at": utc_isoformat(observation.available_at),
        "visible_from": utc_isoformat(observation.visible_from),
    }


def _observation_payload(observation) -> dict[str, Any]:
    return {
        **_zone_definition_payload(observation),
        "snapshot_id": observation.snapshot_id,
        "as_of": utc_isoformat(observation.as_of),
        "visible_until": (
            None
            if observation.visible_until is None
            else utc_isoformat(observation.visible_until)
        ),
        "status": observation.status.value,
        "touch_count": observation.touch_count,
        "fakeout_count": observation.fakeout_count,
        "pending_breach_count": observation.pending_breach_count,
        "age_bars": observation.age_bars,
        "last_interaction_at": (
            None
            if observation.last_interaction_at is None
            else utc_isoformat(observation.last_interaction_at)
        ),
        "runtime_updated_at": utc_isoformat(observation.runtime_updated_at),
        "observation_id": observation.observation_id,
    }


def _event_payload(event) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "snapshot_id": event.snapshot_id,
        "snapshot_as_of": utc_isoformat(event.snapshot_as_of),
        "zone_id": event.zone_id,
        "event_type": event.event_type.value,
        "timestamp": utc_isoformat(event.timestamp),
        "price": event.price,
        "bar_id": event.bar_id,
    }


def _trace_payload(result: TrialResult) -> dict[str, Any]:
    trace = result.trace
    return {
        "schema_version": trace.schema_version,
        "state_key": _state_key_payload(trace.state_key),
        "config_hash": trace.config_hash,
        "field_provenance": [list(pair) for pair in trace.field_provenance],
        "snapshots": [
            {
                "snapshot_id": reference.snapshot_id,
                "as_of": utc_isoformat(reference.as_of),
            }
            for reference in trace.snapshots
        ],
        "zone_observations": [_observation_payload(observation) for observation in trace.zone_observations],
        "events": [_event_payload(event) for event in trace.events],
        "trace_id": trace.trace_id,
    }


def _diagnostics_payload(result: TrialResult) -> dict[str, Any]:
    diagnostics = result.diagnostics
    return {
        "trace_id": diagnostics.trace_id,
        "snapshot_count": diagnostics.snapshot_count,
        "zone_count": diagnostics.zone_count,
        "support_zone_count": diagnostics.support_zone_count,
        "resistance_zone_count": diagnostics.resistance_zone_count,
        "created_event_count": diagnostics.created_event_count,
        "touched_event_count": diagnostics.touched_event_count,
        "breach_started_event_count": diagnostics.breach_started_event_count,
        "false_breakout_event_count": diagnostics.false_breakout_event_count,
        "break_confirmed_event_count": diagnostics.break_confirmed_event_count,
        "expired_event_count": diagnostics.expired_event_count,
        "max_live_zone_count": diagnostics.max_live_zone_count,
        "final_live_zone_count": diagnostics.final_live_zone_count,
        "left_censored_zone_count": diagnostics.left_censored_zone_count,
        "right_censored_zone_count": diagnostics.right_censored_zone_count,
        "snapshots": [
            {
                "snapshot_id": snapshot.snapshot_id,
                "as_of": utc_isoformat(snapshot.as_of),
                "active_zone_count": snapshot.active_zone_count,
                "pending_zone_count": snapshot.pending_zone_count,
                "live_zone_count": snapshot.live_zone_count,
                "new_terminal_zone_count": snapshot.new_terminal_zone_count,
                "event_count": snapshot.event_count,
            }
            for snapshot in diagnostics.snapshots
        ],
        "zones": [
            {
                "zone_id": zone.zone_id,
                "side": zone.side.value,
                "render_kind": zone.render_kind.value,
                "available_at": utc_isoformat(zone.available_at),
                "terminal_at": (
                    None if zone.terminal_at is None else utc_isoformat(zone.terminal_at)
                ),
                "final_status": zone.final_status.value,
                "lifetime_bars": zone.lifetime_bars,
                "touch_count": zone.touch_count,
                "fakeout_count": zone.fakeout_count,
                "first_touch_at": (
                    None
                    if zone.first_touch_at is None
                    else utc_isoformat(zone.first_touch_at)
                ),
                "time_to_first_touch_bars": zone.time_to_first_touch_bars,
                "status_bar_counts": [
                    [status.value, count] for status, count in zone.status_bar_counts
                ],
                "left_censored": zone.left_censored,
                "right_censored": zone.right_censored,
                "diagnostic_id": zone.diagnostic_id,
            }
            for zone in diagnostics.zones
        ],
        "diagnostics_id": diagnostics.diagnostics_id,
    }


def _resolved_sr_payload(result: TrialResult) -> dict[str, Any]:
    config = result.resolved_sr_config
    return {
        "version": config.version,
        "asset": config.asset,
        "timeframe": config.timeframe,
        "detection": {
            "pivot_span_bars": config.detection.pivot_span_bars,
            "zone_half_width_atr": config.detection.zone_half_width_atr,
        },
        "association": {"merge_distance_atr": config.association.merge_distance_atr},
        "lifecycle": {
            "touch_tolerance_atr": config.lifecycle.touch_tolerance_atr,
            "break_buffer_atr": config.lifecycle.break_buffer_atr,
            "break_confirm_closes": config.lifecycle.break_confirm_closes,
            "max_age_bars": config.lifecycle.max_age_bars,
        },
        "runtime": {"max_active_zones": config.runtime.max_active_zones},
        "field_provenance": [list(pair) for pair in config.field_provenance],
        "resolved_config_hash": config.resolved_config_hash,
    }


def _manifest_semantic_payload(
    result: TrialResult,
    *,
    implementation_commit: str,
    members: tuple[BundleMember, ...],
    chart_identity_hash: str,
) -> dict[str, Any]:
    dataset = result.dataset
    provider_since_ms, provider_until_ms = effective_provider_request_bounds(
        dataset.requested_since,
        dataset.requested_until,
    )
    member_payload = [
        {"name": member.name, "sha256": member.sha256, "byte_length": member.byte_length}
        for member in members
    ]
    return {
        "schema_version": SR_BASELINE_TRIAL_SCHEMA_VERSION,
        "trial_name": result.trial.trial_name,
        "trial": result.trial.to_payload(),
        "provider_adapter": "apps.ingestion_app.adapters.binance_native.BinanceNativeAdapter",
        "requested_since": utc_isoformat(dataset.requested_since),
        "requested_until": utc_isoformat(dataset.requested_until),
        "actual_since": utc_isoformat(dataset.actual_since),
        "actual_until": utc_isoformat(dataset.actual_until),
        "raw_row_count": dataset.raw_row_count,
        "warmup_row_count": result.atr.warmup_count,
        "model_row_count": result.atr.model_bar_count,
        "gap_policy": dataset.gap_policy,
        "closed_bar_policy": "closed_at=open_time+1d",
        "window_policy": BASELINE_WINDOW_POLICY,
        "provider_request": {
            "startTime": provider_since_ms,
            "endTime": provider_until_ms,
        },
        "source_bars_sha256": next(member.sha256 for member in members if member.name == "source_bars.json"),
        "resolved_sr_config": _resolved_sr_payload(result),
        "resolved_input_hash": result.resolved_input.resolved_input_hash,
        "input_field_provenance": [list(pair) for pair in result.resolved_input.field_provenance],
        "atr": result.atr.to_payload(),
        "implementation_commit": implementation_commit,
        "sr_schema_version": "1.0",
        "evaluation_schema_version": result.trace.schema_version,
        "trace_id": result.trace.trace_id,
        "diagnostics_id": result.diagnostics.diagnostics_id,
        "viewer_library": result.trial.viewer.library,
        "viewer_library_version": result.trial.viewer.library_version,
        "chart_payload_schema_version": "1.0",
        "chart_payload_identity_hash": chart_identity_hash,
        "members": member_payload,
    }


def _manifest_payload(
    manifest: EvidenceManifest,
    *,
    semantic_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        **semantic_payload,
        "bundle_id": manifest.bundle_id,
    }


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json_load(path: Path) -> Any:
    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"invalid JSON evidence member: {path}: {exc}") from exc


def _validate_manifest_identity(
    payload: dict[str, Any],
    chart_payload: dict[str, Any],
    model_payload: dict[str, Any],
) -> None:
    identity = payload.get("bundle_id_semantic_payload")
    bundle_id = payload.get("bundle_id")
    if type(identity) is not dict or type(bundle_id) is not str:
        raise ValueError("bundle identity payload is missing")
    if deterministic_hash(identity) != bundle_id:
        raise ValueError("bundle_id does not match bundle_id_semantic_payload")
    expected_keys = set(identity) | {"bundle_id", "bundle_id_semantic_payload"}
    if set(payload) != expected_keys:
        raise ValueError("manifest semantic fields do not match bundle identity")
    for key, expected in identity.items():
        if key == "members":
            continue
        if payload.get(key, _MISSING) != expected:
            raise ValueError(f"manifest semantic field mismatch: {key}")

    actual_members = payload.get("members")
    identity_members = identity.get("members")
    if type(actual_members) is not list or type(identity_members) is not list:
        raise ValueError("bundle identity members are malformed")
    if identity.get("bundle_id_basis_members") != identity_members:
        raise ValueError("bundle identity basis members do not match members")
    actual_by_name = {member["name"]: member for member in actual_members}
    identity_by_name = {
        member.get("name"): member
        for member in identity_members
        if type(member) is dict
    }
    if set(actual_by_name) != set(identity_by_name):
        raise ValueError("bundle identity member names do not match")
    for name in actual_by_name:
        if name != "chart_payload.json" and actual_by_name[name] != identity_by_name[name]:
            raise ValueError(f"bundle identity member mismatch: {name}")
    if payload.get("source_bars_sha256") != actual_by_name["source_bars.json"]["sha256"]:
        raise ValueError("source_bars_sha256 does not match member metadata")
    if chart_payload.get("bundle_id") != bundle_id:
        raise ValueError("chart payload bundle_id does not match manifest")
    if chart_payload_identity(chart_payload) != payload.get("chart_payload_identity_hash"):
        raise ValueError("chart payload identity does not match manifest")
    model_bars = model_payload.get("bars")
    if type(model_bars) is not list or not model_bars or type(model_bars[0]) is not dict:
        raise ValueError("model bars are malformed")
    atr = payload.get("atr")
    if type(atr) is not dict:
        raise ValueError("manifest ATR provenance is malformed")
    if model_payload.get("atr") != atr:
        raise ValueError("model ATR provenance does not match manifest")
    if atr.get("first_valid_at") != model_bars[0].get("closed_at"):
        raise ValueError("ATR first_valid_at does not match first model bar closed_at")


def validate_bundle(bundle_path: str | Path) -> dict[str, Any]:
    """Validate manifest/member bytes before a viewer serves a bundle."""
    bundle = Path(bundle_path)
    if not bundle.is_dir():
        raise ValueError("bundle path must be a directory")
    manifest_path = bundle / "manifest.json"
    payload = _json_load(manifest_path)
    if type(payload) is not dict or type(payload.get("members")) is not list:
        raise ValueError("manifest must contain member list")
    bundle_id = payload.get("bundle_id")
    if type(bundle_id) is not str or bundle.name != bundle_id:
        raise ValueError("bundle directory does not match manifest bundle_id")
    members = payload["members"]
    if any(type(member) is not dict for member in members):
        raise ValueError("malformed bundle member metadata")
    names = [member.get("name") for member in members]
    if any(type(name) is not str for name in names):
        raise ValueError("bundle member names must be strings")
    if set(names) != set(_MEMBER_NAMES) or len(names) != len(_MEMBER_NAMES):
        raise ValueError("manifest members do not match bundle schema")
    expected_names = {"manifest.json", *_MEMBER_NAMES}
    if {path.name for path in bundle.iterdir()} != expected_names:
        raise ValueError("bundle contains unexpected files")
    for member in members:
        if set(member) != {"name", "sha256", "byte_length"}:
            raise ValueError("malformed bundle member metadata")
        if (
            type(member["name"]) is not str
            or type(member["sha256"]) is not str
            or type(member["byte_length"]) is not int
            or member["byte_length"] < 0
        ):
            raise ValueError("malformed bundle member metadata")
        if "/" in member["name"] or "\\" in member["name"] or ".." in Path(member["name"]).parts:
            raise ValueError("invalid bundle member name")
        path = bundle / member["name"]
        data = path.read_bytes()
        if _file_hash(data) != member["sha256"] or len(data) != member["byte_length"]:
            raise ValueError(f"bundle member hash mismatch: {member['name']}")
    chart_payload = _json_load(bundle / "chart_payload.json")
    if type(chart_payload) is not dict:
        raise ValueError("chart payload must be a mapping")
    model_payload = _json_load(bundle / "model_bars.json")
    if type(model_payload) is not dict:
        raise ValueError("model payload must be a mapping")
    _validate_manifest_identity(payload, chart_payload, model_payload)
    return payload


def publish_bundle(
    result: TrialResult,
    *,
    repo_root: str | Path,
    implementation_commit: str,
) -> BundlePublication:
    """Write one deterministic content-addressed evidence bundle atomically."""
    root = Path(repo_root).resolve()
    output_root = (root / result.trial.output_root).resolve()
    if root not in output_root.parents:
        raise ValueError("output_root escaped repository root")
    output_root.mkdir(parents=True, exist_ok=True)

    source_payload = _source_payload(result)
    model_payload = _model_payload(result)
    trace_payload = _trace_payload(result)
    diagnostics_payload = _diagnostics_payload(result)
    chart_unbound = build_chart_payload(
        trial=result.trial,
        bundle_id=None,
        resolved_sr_config=result.resolved_sr_config,
        resolved_input=result.resolved_input,
        source_bars=result.dataset.bars,
        trace=result.trace,
        diagnostics=result.diagnostics,
    )
    chart_identity_hash = chart_payload_identity(chart_unbound)
    prebind_payloads = {
        "source_bars.json": _bytes(source_payload),
        "model_bars.json": _bytes(model_payload),
        "trace.json": _bytes(trace_payload),
        "diagnostics.json": _bytes(diagnostics_payload),
        "chart_payload.json": _bytes(chart_unbound),
    }
    prebind_members = tuple(
        BundleMember(name=name, sha256=_file_hash(data), byte_length=len(data))
        for name, data in prebind_payloads.items()
    )
    bundle_id_basis = _manifest_semantic_payload(
        result,
        implementation_commit=implementation_commit,
        members=prebind_members,
        chart_identity_hash=chart_identity_hash,
    )
    bundle_id_basis["bundle_id_basis_members"] = [
        {"name": member.name, "sha256": member.sha256, "byte_length": member.byte_length}
        for member in prebind_members
    ]
    bundle_id = deterministic_hash(bundle_id_basis)
    chart_payload = build_chart_payload(
        trial=result.trial,
        bundle_id=bundle_id,
        resolved_sr_config=result.resolved_sr_config,
        resolved_input=result.resolved_input,
        source_bars=result.dataset.bars,
        trace=result.trace,
        diagnostics=result.diagnostics,
    )
    payloads = {
        "source_bars.json": prebind_payloads["source_bars.json"],
        "model_bars.json": prebind_payloads["model_bars.json"],
        "trace.json": prebind_payloads["trace.json"],
        "diagnostics.json": prebind_payloads["diagnostics.json"],
        "chart_payload.json": _bytes(chart_payload),
    }
    members = tuple(
        BundleMember(name=name, sha256=_file_hash(data), byte_length=len(data))
        for name, data in payloads.items()
    )
    semantic_payload = _manifest_semantic_payload(
        result,
        implementation_commit=implementation_commit,
        members=members,
        chart_identity_hash=chart_identity_hash,
    )
    semantic_payload["bundle_id_basis_members"] = [
        {"name": member.name, "sha256": member.sha256, "byte_length": member.byte_length}
        for member in prebind_members
    ]
    semantic_payload["bundle_id_semantic_payload"] = bundle_id_basis
    manifest = EvidenceManifest(
        schema_version=SR_BASELINE_TRIAL_SCHEMA_VERSION,
        trial=result.trial,
        provider_adapter="apps.ingestion_app.adapters.binance_native.BinanceNativeAdapter",
        dataset=result.dataset,
        resolved_sr_config=result.resolved_sr_config,
        resolved_input=result.resolved_input,
        atr=result.atr,
        implementation_commit=implementation_commit,
        sr_schema_version="1.0",
        evaluation_schema_version=result.trace.schema_version,
        trace_id=result.trace.trace_id,
        diagnostics_id=result.diagnostics.diagnostics_id,
        chart_payload_schema_version="1.0",
        members=members,
        bundle_id=bundle_id,
    )
    manifest_bytes = _bytes(_manifest_payload(manifest, semantic_payload=semantic_payload))
    output_path = output_root / bundle_id
    if output_path.exists():
        if not output_path.is_dir():
            raise ValueError("bundle path collision is not a directory")
        expected = {"manifest.json": manifest_bytes, **payloads}
        if {path.name for path in output_path.iterdir()} != set(expected):
            raise ValueError("existing bundle contains unexpected files")
        for name, data in expected.items():
            if (output_path / name).read_bytes() != data:
                raise ValueError(f"existing bundle collision or byte mismatch: {name}")
        validate_bundle(output_path)
        return BundlePublication(bundle_id=bundle_id, output_path=output_path, manifest=manifest)

    temporary = Path(tempfile.mkdtemp(prefix=f".{bundle_id}.", dir=output_root))
    try:
        for name, data in payloads.items():
            (temporary / name).write_bytes(data)
        (temporary / "manifest.json").write_bytes(manifest_bytes)
        os.replace(temporary, output_path)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    validate_bundle(output_path)
    return BundlePublication(bundle_id=bundle_id, output_path=output_path, manifest=manifest)


__all__ = ["publish_bundle", "validate_bundle"]
