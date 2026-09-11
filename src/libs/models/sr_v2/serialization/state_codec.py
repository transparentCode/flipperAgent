"""Deterministic, duplicate-key-safe codec for bounded SR v2 state."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import isfinite
from typing import Any

from ..contracts import SR_V2_SCHEMA_VERSION, LifecycleState, ZoneSide
from ..domain.state import SRState
from ..domain.zones import ZoneLineage, ZoneRecord


def _encode(value: Any) -> Any:
    if isinstance(value, ZoneSide):
        return {"__zone_side__": value.value}
    if isinstance(value, LifecycleState):
        return {"__lifecycle__": value.value}
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("non-finite state values are unsupported")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite state values are unsupported")
        return {"__decimal__": str(value)}
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("state datetimes must use UTC")
        return {"__datetime__": value.astimezone(UTC).isoformat(timespec="microseconds")}
    if isinstance(value, timedelta):
        return {
            "__timedelta__": value.days * 86_400_000_000
            + value.seconds * 1_000_000
            + value.microseconds
        }
    if isinstance(value, ZoneLineage):
        return {"__zone_lineage__": _encode({name: getattr(value, name) for name in value.__dataclass_fields__})}
    if isinstance(value, ZoneRecord):
        return {"__zone_record__": _encode({name: getattr(value, name) for name in value.__dataclass_fields__})}
    if isinstance(value, SRState):
        return _encode({name: getattr(value, name) for name in value.__dataclass_fields__})
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("state mapping keys must be strings")
        return {key: _encode(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [_encode(item) for item in value]
    raise TypeError(f"unsupported state value: {type(value).__name__}")


def _decode(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_decode(item) for item in value)
    if not isinstance(value, dict):
        return value
    if set(value) == {"__decimal__"}:
        return Decimal(value["__decimal__"])
    if set(value) == {"__datetime__"}:
        return datetime.fromisoformat(value["__datetime__"])
    if set(value) == {"__timedelta__"}:
        micros = value["__timedelta__"]
        if isinstance(micros, bool) or not isinstance(micros, int):
            raise ValueError("invalid encoded timedelta")
        return timedelta(microseconds=micros)
    if set(value) == {"__zone_side__"}:
        return ZoneSide(value["__zone_side__"])
    if set(value) == {"__lifecycle__"}:
        return LifecycleState(value["__lifecycle__"])
    if set(value) == {"__zone_lineage__"}:
        return ZoneLineage(**_decode(value["__zone_lineage__"]))
    if set(value) == {"__zone_record__"}:
        return ZoneRecord(**_decode(value["__zone_record__"]))
    return {key: _decode(item) for key, item in value.items()}


def encode_state(state: SRState) -> bytes:
    if not isinstance(state, SRState):
        raise TypeError("state must be SRState")
    payload = json.dumps(
        _encode(state),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(payload) > 16 * 1024 * 1024:
        raise ValueError("SR v2 state payload exceeds 16 MiB")
    return payload


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate state key: {key}")
        result[key] = value
    return result


def decode_state(
    payload: bytes | str,
    *,
    expected_config_fingerprint: str | None = None,
    expected_venue: str | None = None,
    expected_instrument_id: str | None = None,
    expected_asset: str | None = None,
    max_active_lineages: int | None = None,
    max_terminal_tombstones: int | None = None,
) -> SRState:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes or str")
    if len(payload) > 16 * 1024 * 1024:
        raise ValueError("SR v2 state payload exceeds 16 MiB")
    try:
        raw = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
        decoded = _decode(raw)
    except Exception as exc:
        raise ValueError("invalid SR v2 state JSON") from exc
    if not isinstance(decoded, dict):
        raise TypeError("SR v2 state root must be an object")
    allowed = {
        "schema_version",
        "config_fingerprint",
        "generation",
        "venue",
        "instrument_id",
        "asset",
        "last_trigger_at",
        "source_cutoffs",
        "source_fingerprints",
        "source_fingerprint_sequences",
        "active_lineages",
        "terminal_tombstones",
    }
    if set(decoded) != allowed:
        raise ValueError("SR v2 state schema keys do not match exactly")
    state = SRState(**decoded)
    if state.schema_version != SR_V2_SCHEMA_VERSION:
        raise ValueError("unsupported SR v2 state schema version")
    expected_identity = {
        "config_fingerprint": expected_config_fingerprint,
        "venue": expected_venue,
        "instrument_id": expected_instrument_id,
        "asset": expected_asset,
    }
    for field_name, expected in expected_identity.items():
        if expected is not None and getattr(state, field_name) != expected:
            raise ValueError(f"SR v2 state {field_name} identity mismatch")
    if max_active_lineages is not None and len(state.active_lineages) > max_active_lineages:
        raise ValueError("SR v2 active lineage bound exceeded")
    if max_terminal_tombstones is not None and len(state.terminal_tombstones) > max_terminal_tombstones:
        raise ValueError("SR v2 tombstone bound exceeded")
    if encode_state(state) != payload:
        raise ValueError("SR v2 state is not canonical")
    return state


__all__ = ["decode_state", "encode_state"]
