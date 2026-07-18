"""Canonical, pure JSON codec for SR aggregate state."""

from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any

from libs.models.sr.domain.bars import ClosedBar, SRStateKey
from libs.models.sr.domain.errors import ContractValidationError
from libs.models.sr.domain.geometry import ZoneGeometry
from libs.models.sr.domain.identity import (
    canonical_json,
    deterministic_hash,
    require_utc,
    utc_isoformat,
)
from libs.models.sr.domain.state import SR_SCHEMA_VERSION, SRState
from libs.models.sr.domain.zones import ZoneDefinition, ZoneRecord, ZoneRuntimeState


_CODEC_NAME = "sr-state-json"
_CODEC_VERSION = 1
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _mapping(value: Any, *, path: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractValidationError(f"{path} must be a JSON object")
    return value


def _keys(value: dict[str, Any], expected: set[str], *, path: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ContractValidationError(
            f"invalid keys at {path}: missing={missing}, unknown={unknown}"
        )


def _sha256(value: Any, *, path: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise ContractValidationError(
            f"{path} must be a lowercase SHA-256 hex string"
        )
    return value


def _timestamp(value: Any, *, path: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise ContractValidationError(
            f"{path} must be a canonical UTC timestamp ending in Z"
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        normalized = utc_isoformat(parsed)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{path} must be a valid UTC timestamp") from exc
    if normalized != value:
        raise ContractValidationError(f"{path} must use canonical UTC format")
    return require_utc(parsed, field_name=path)


def _state_key(value: Any, *, path: str) -> SRStateKey:
    data = _mapping(value, path=path)
    _keys(data, {"venue", "symbol", "timeframe"}, path=path)
    return SRStateKey(
        venue=data["venue"],
        symbol=data["symbol"],
        timeframe=data["timeframe"],
    )


def _geometry(value: Any, *, path: str) -> ZoneGeometry:
    data = _mapping(value, path=path)
    _keys(data, {"center", "half_width"}, path=path)
    return ZoneGeometry(center=data["center"], half_width=data["half_width"])


def _state_key_payload(value: SRStateKey) -> dict[str, Any]:
    return {
        "venue": value.venue,
        "symbol": value.symbol,
        "timeframe": value.timeframe,
    }


def _geometry_payload(value: ZoneGeometry) -> dict[str, Any]:
    return {"center": value.center, "half_width": value.half_width}


def _definition_payload(value: ZoneDefinition) -> dict[str, Any]:
    return {
        "state_key": _state_key_payload(value.state_key),
        "side": value.side.value,
        "geometry": _geometry_payload(value.geometry),
        "source": value.source,
        "created_at": utc_isoformat(value.created_at),
        "available_at": utc_isoformat(value.available_at),
        "atr_at_creation": value.atr_at_creation,
        "config_hash": value.config_hash,
        "zone_id": value.zone_id,
    }


def _runtime_payload(value: ZoneRuntimeState) -> dict[str, Any]:
    return {
        "zone_id": value.zone_id,
        "status": value.status.value,
        "touch_count": value.touch_count,
        "fakeout_count": value.fakeout_count,
        "pending_breach_count": value.pending_breach_count,
        "age_bars": value.age_bars,
        "last_interaction_at": (
            None
            if value.last_interaction_at is None
            else utc_isoformat(value.last_interaction_at)
        ),
        "updated_at": utc_isoformat(value.updated_at),
    }


def _record_payload(value: ZoneRecord) -> dict[str, Any]:
    return {
        "definition": _definition_payload(value.definition),
        "runtime": _runtime_payload(value.runtime),
    }


def _bar_payload(value: ClosedBar) -> dict[str, Any]:
    return {
        "state_key": _state_key_payload(value.state_key),
        "bar_id": value.bar_id,
        "closed_at": utc_isoformat(value.closed_at),
        "open": value.open,
        "high": value.high,
        "low": value.low,
        "close": value.close,
        "atr_at_close": value.atr_at_close,
    }


def _state_payload(value: SRState) -> dict[str, Any]:
    return {
        "schema_version": value.schema_version,
        "state_key": _state_key_payload(value.state_key),
        "config_hash": value.config_hash,
        "last_processed_bar": value.last_processed_bar,
        "zones": [_record_payload(record) for record in value.zones],
        "recent_bars": [_bar_payload(bar) for bar in value.recent_bars],
    }


def _envelope(value: SRState) -> dict[str, Any]:
    state_payload = _state_payload(value)
    return {
        "codec_name": _CODEC_NAME,
        "codec_version": _CODEC_VERSION,
        "payload_hash": deterministic_hash(state_payload),
        "state": state_payload,
    }


def encode_state(state: SRState) -> str:
    """Encode SR state as deterministic canonical JSON text."""
    if type(state) is not SRState:
        raise ContractValidationError("state must be exactly SRState")
    if state.schema_version != SR_SCHEMA_VERSION:
        raise ContractValidationError(
            f"unsupported SR schema version: {state.schema_version!r}"
        )
    return canonical_json(_envelope(state))


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> Any:
    raise ContractValidationError(f"non-finite JSON number is not allowed: {value}")


def _decode_definition(value: Any, *, path: str) -> ZoneDefinition:
    data = _mapping(value, path=path)
    _keys(
        data,
        {
            "state_key",
            "side",
            "geometry",
            "source",
            "created_at",
            "available_at",
            "atr_at_creation",
            "config_hash",
            "zone_id",
        },
        path=path,
    )
    definition = ZoneDefinition(
        state_key=_state_key(data["state_key"], path=f"{path}.state_key"),
        side=data["side"],
        geometry=_geometry(data["geometry"], path=f"{path}.geometry"),
        source=data["source"],
        created_at=_timestamp(data["created_at"], path=f"{path}.created_at"),
        available_at=_timestamp(
            data["available_at"], path=f"{path}.available_at"
        ),
        atr_at_creation=data["atr_at_creation"],
        config_hash=data["config_hash"],
    )
    if _sha256(data["zone_id"], path=f"{path}.zone_id") != definition.zone_id:
        raise ContractValidationError(f"{path}.zone_id does not match content")
    return definition


def _decode_runtime(value: Any, *, path: str) -> ZoneRuntimeState:
    data = _mapping(value, path=path)
    _keys(
        data,
        {
            "zone_id",
            "status",
            "touch_count",
            "fakeout_count",
            "pending_breach_count",
            "age_bars",
            "last_interaction_at",
            "updated_at",
        },
        path=path,
    )
    last_interaction_at = data["last_interaction_at"]
    if last_interaction_at is not None:
        last_interaction_at = _timestamp(
            last_interaction_at,
            path=f"{path}.last_interaction_at",
        )
    runtime = ZoneRuntimeState(
        zone_id=_sha256(data["zone_id"], path=f"{path}.zone_id"),
        status=data["status"],
        touch_count=data["touch_count"],
        fakeout_count=data["fakeout_count"],
        pending_breach_count=data["pending_breach_count"],
        age_bars=data["age_bars"],
        last_interaction_at=last_interaction_at,
        updated_at=_timestamp(data["updated_at"], path=f"{path}.updated_at"),
    )
    return runtime


def _decode_record(value: Any, *, path: str) -> ZoneRecord:
    data = _mapping(value, path=path)
    _keys(data, {"definition", "runtime"}, path=path)
    return ZoneRecord(
        definition=_decode_definition(data["definition"], path=f"{path}.definition"),
        runtime=_decode_runtime(data["runtime"], path=f"{path}.runtime"),
    )


def _decode_bar(value: Any, *, path: str) -> ClosedBar:
    data = _mapping(value, path=path)
    _keys(
        data,
        {
            "state_key",
            "bar_id",
            "closed_at",
            "open",
            "high",
            "low",
            "close",
            "atr_at_close",
        },
        path=path,
    )
    return ClosedBar(
        state_key=_state_key(data["state_key"], path=f"{path}.state_key"),
        bar_id=data["bar_id"],
        closed_at=_timestamp(data["closed_at"], path=f"{path}.closed_at"),
        open=data["open"],
        high=data["high"],
        low=data["low"],
        close=data["close"],
        atr_at_close=data["atr_at_close"],
    )


def _decode_state(value: Any) -> tuple[SRState, dict[str, Any]]:
    data = _mapping(value, path="state")
    _keys(
        data,
        {
            "schema_version",
            "state_key",
            "config_hash",
            "last_processed_bar",
            "zones",
            "recent_bars",
        },
        path="state",
    )
    zones = data["zones"]
    recent_bars = data["recent_bars"]
    if type(zones) is not list:
        raise ContractValidationError("state.zones must be a JSON array")
    if type(recent_bars) is not list:
        raise ContractValidationError("state.recent_bars must be a JSON array")
    state = SRState(
        schema_version=data["schema_version"],
        state_key=_state_key(data["state_key"], path="state.state_key"),
        config_hash=data["config_hash"],
        last_processed_bar=data["last_processed_bar"],
        zones=tuple(
            _decode_record(record, path=f"state.zones[{idx}]")
            for idx, record in enumerate(zones)
        ),
        recent_bars=tuple(
            _decode_bar(bar, path=f"state.recent_bars[{idx}]")
            for idx, bar in enumerate(recent_bars)
        ),
    )
    return state, data


def decode_state(payload: str) -> SRState:
    """Decode and strictly validate canonical SR state JSON text."""
    if type(payload) is not str:
        raise ContractValidationError("payload must be a string")
    try:
        envelope = json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except ContractValidationError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractValidationError("payload must be valid JSON") from exc

    envelope = _mapping(envelope, path="envelope")
    _keys(
        envelope,
        {"codec_name", "codec_version", "payload_hash", "state"},
        path="envelope",
    )
    if envelope["codec_name"] != _CODEC_NAME:
        raise ContractValidationError("unsupported SR state codec name")
    if type(envelope["codec_version"]) is not int:
        raise ContractValidationError("codec_version must be integer 1")
    if envelope["codec_version"] != _CODEC_VERSION:
        raise ContractValidationError("unsupported SR state codec version")
    payload_hash = _sha256(envelope["payload_hash"], path="payload_hash")
    state, state_payload = _decode_state(envelope["state"])
    expected_hash = deterministic_hash(state_payload)
    if payload_hash != expected_hash:
        raise ContractValidationError("payload_hash does not match state payload")

    canonical = encode_state(state)
    if payload != canonical:
        raise ContractValidationError("payload is not canonical SR state JSON")
    return state


__all__ = ["decode_state", "encode_state"]
