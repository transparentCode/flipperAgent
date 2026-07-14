"""Deterministic identity and canonical serialization for SR domain objects.

Identity is SHA-256 over canonical JSON with sorted keys, enum values as
strings, UTC ISO timestamps, and NaN/Inf rejected.  Each object's own ID
field is excluded from the hash payload used to compute that ID.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import math
from typing import Any, Mapping


class ContractValidationError(ValueError):
    """Raised when an SR contract invariant is violated."""


def require_utc(timestamp: datetime, *, field_name: str = "timestamp") -> datetime:
    """Reject naive timestamps and normalize aware timestamps to UTC."""
    if not isinstance(timestamp, datetime):
        raise ContractValidationError(f"{field_name} must be a datetime")
    if timestamp.utcoffset() is None:
        raise ContractValidationError(f"{field_name} must be timezone-aware")
    return timestamp.astimezone(timezone.utc)


def utc_isoformat(timestamp: datetime) -> str:
    return require_utc(timestamp).isoformat().replace("+00:00", "Z")


def _number(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ContractValidationError(f"{field_name} must be finite")
    if result == 0.0:
        return 0.0
    return result


def _primitive(value: Any) -> Any:
    if isinstance(value, datetime):
        return utc_isoformat(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float):
        return _number(value, field_name="serialized float")
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Mapping):
        return {key: _primitive(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    if is_dataclass(value):
        return {
            item.name: _primitive(getattr(value, item.name)) for item in fields(value)
        }
    raise ContractValidationError(
        f"unsupported canonical value type: {type(value)!r}"
    )


def canonical_json(value: Any) -> str:
    return json.dumps(
        _primitive(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def deterministic_hash(payload: Any) -> str:
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _identity_payload(obj: Any, exclude_id_field: str) -> dict[str, Any]:
    raw = _primitive(obj)
    if not isinstance(raw, dict):
        raise ContractValidationError("identity payload must be a mapping")
    raw.pop(exclude_id_field, None)
    return raw


def _identity_payload_for_init(obj: Any, exclude_id_field: str) -> dict[str, Any]:
    """Build an identity payload for objects whose ID field is init=False.

    Because the ID field does not exist until after __post_init__, this helper
    builds the payload from dataclass fields while skipping the ID field.
    """
    if not is_dataclass(obj):
        raise ContractValidationError("identity payload must be a dataclass")
    raw = {
        item.name: _primitive(getattr(obj, item.name))
        for item in fields(obj)
        if item.name != exclude_id_field
    }
    return raw


def hash_candidate_level(level: Any) -> str:
    return deterministic_hash(_identity_payload_for_init(level, "candidate_id"))


def hash_zone_definition(definition: Any) -> str:
    return deterministic_hash(_identity_payload_for_init(definition, "zone_id"))


def hash_event(event: Any) -> str:
    return deterministic_hash(_identity_payload_for_init(event, "event_id"))


def hash_snapshot(snapshot: Any) -> str:
    return deterministic_hash(_identity_payload_for_init(snapshot, "snapshot_id"))
