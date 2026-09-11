"""Deterministic tagged JSON codec for the bounded D9A model-state vocabulary."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from math import isfinite
from typing import Any

from libs.contracts.decision import (
    FrozenMapping,
    ModelState,
    freeze_model_state,
    require_utc,
)


class StateCodecError(ValueError):
    """Raised when checkpoint state is not in the supported semantic vocabulary."""


def _encode(value: Any, *, active: set[int], path: str) -> Any:
    if value is None:
        return {"tag": "none"}
    if isinstance(value, bool):
        return {"tag": "bool", "value": value}
    if isinstance(value, int):
        return {"tag": "int", "value": str(value)}
    if isinstance(value, float):
        if not isfinite(value):
            raise StateCodecError(f"non-finite float at {path}")
        return {"tag": "float", "value": value.hex()}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise StateCodecError(f"non-finite Decimal at {path}")
        return {"tag": "decimal", "value": str(value)}
    if isinstance(value, str):
        return {"tag": "str", "value": value}
    if isinstance(value, bytes):
        return {
            "tag": "bytes",
            "value": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, datetime):
        try:
            require_utc(value, field_name=path)
        except (TypeError, ValueError) as exc:
            raise StateCodecError(str(exc)) from exc
        return {
            "tag": "datetime",
            "value": value.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
    if isinstance(value, timedelta):
        return {
            "tag": "timedelta",
            "microseconds": value.days * 86_400_000_000
            + value.seconds * 1_000_000
            + value.microseconds,
        }
    object_id = id(value)
    if isinstance(value, Mapping):
        if object_id in active:
            raise StateCodecError(f"cyclic mapping at {path}")
        active.add(object_id)
        try:
            if any(not isinstance(key, str) for key in value):
                raise StateCodecError(f"mapping keys must be strings at {path}")
            return {
                "tag": "mapping",
                "value": [
                    [key, _encode(value[key], active=active, path=f"{path}.{key}")]
                    for key in sorted(value)
                ],
            }
        finally:
            active.remove(object_id)
    if isinstance(value, tuple):
        if object_id in active:
            raise StateCodecError(f"cyclic tuple at {path}")
        active.add(object_id)
        try:
            return {
                "tag": "tuple",
                "value": [
                    _encode(item, active=active, path=f"{path}[{index}]")
                    for index, item in enumerate(value)
                ],
            }
        finally:
            active.remove(object_id)
    if isinstance(value, list):
        if object_id in active:
            raise StateCodecError(f"cyclic list at {path}")
        active.add(object_id)
        try:
            return {
                "tag": "list",
                "value": [
                    _encode(item, active=active, path=f"{path}[{index}]")
                    for index, item in enumerate(value)
                ],
            }
        finally:
            active.remove(object_id)
    raise StateCodecError(
        f"unsupported checkpoint state value at {path}: {type(value).__name__}"
    )


def _exact_mapping(value: object, *, path: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise StateCodecError(f"invalid tagged value at {path}")
    return value


def _decode(value: object, *, path: str) -> Any:
    if not isinstance(value, dict) or not isinstance(value.get("tag"), str):
        raise StateCodecError(f"invalid tagged value at {path}")
    tag = value["tag"]
    if tag == "none":
        _exact_mapping(value, path=path, keys={"tag"})
        return None
    if tag == "bool":
        data = _exact_mapping(value, path=path, keys={"tag", "value"})
        if not isinstance(data["value"], bool):
            raise StateCodecError(f"invalid bool at {path}")
        return data["value"]
    if tag == "int":
        data = _exact_mapping(value, path=path, keys={"tag", "value"})
        if not isinstance(data["value"], str):
            raise StateCodecError(f"invalid int at {path}")
        try:
            return int(data["value"])
        except ValueError as exc:
            raise StateCodecError(f"invalid int at {path}") from exc
    if tag == "float":
        data = _exact_mapping(value, path=path, keys={"tag", "value"})
        if not isinstance(data["value"], str):
            raise StateCodecError(f"invalid float at {path}")
        try:
            result = float.fromhex(data["value"])
        except ValueError as exc:
            raise StateCodecError(f"invalid float at {path}") from exc
        if not isfinite(result):
            raise StateCodecError(f"non-finite float at {path}")
        return result
    if tag == "decimal":
        data = _exact_mapping(value, path=path, keys={"tag", "value"})
        if not isinstance(data["value"], str):
            raise StateCodecError(f"invalid Decimal at {path}")
        try:
            result = Decimal(data["value"])
        except (InvalidOperation, ValueError) as exc:
            raise StateCodecError(f"invalid Decimal at {path}") from exc
        if not result.is_finite():
            raise StateCodecError(f"non-finite Decimal at {path}")
        return result
    if tag == "str":
        data = _exact_mapping(value, path=path, keys={"tag", "value"})
        if not isinstance(data["value"], str):
            raise StateCodecError(f"invalid string at {path}")
        return data["value"]
    if tag == "bytes":
        data = _exact_mapping(value, path=path, keys={"tag", "value"})
        if not isinstance(data["value"], str):
            raise StateCodecError(f"invalid bytes at {path}")
        try:
            return base64.b64decode(data["value"].encode("ascii"), validate=True)
        except (ValueError, UnicodeError) as exc:
            raise StateCodecError(f"invalid bytes at {path}") from exc
    if tag == "datetime":
        data = _exact_mapping(value, path=path, keys={"tag", "value"})
        if not isinstance(data["value"], str) or not data["value"].endswith("Z"):
            raise StateCodecError(f"invalid datetime at {path}")
        try:
            parsed = datetime.fromisoformat(data["value"])
            require_utc(parsed, field_name=path)
        except (TypeError, ValueError) as exc:
            raise StateCodecError(f"invalid datetime at {path}") from exc
        return parsed
    if tag == "timedelta":
        data = _exact_mapping(value, path=path, keys={"tag", "microseconds"})
        if isinstance(data["microseconds"], bool) or not isinstance(
            data["microseconds"], int
        ):
            raise StateCodecError(f"invalid timedelta at {path}")
        return timedelta(microseconds=data["microseconds"])
    if tag in {"tuple", "list"}:
        data = _exact_mapping(value, path=path, keys={"tag", "value"})
        if not isinstance(data["value"], list):
            raise StateCodecError(f"invalid sequence at {path}")
        values = tuple(
            _decode(item, path=f"{path}[{index}]")
            for index, item in enumerate(data["value"])
        )
        return values if tag == "tuple" else list(values)
    if tag == "mapping":
        data = _exact_mapping(value, path=path, keys={"tag", "value"})
        if not isinstance(data["value"], list):
            raise StateCodecError(f"invalid mapping at {path}")
        result: dict[str, Any] = {}
        previous: str | None = None
        for index, pair in enumerate(data["value"]):
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or not isinstance(pair[0], str)
            ):
                raise StateCodecError(f"invalid mapping entry at {path}[{index}]")
            key = pair[0]
            if previous is not None and key <= previous:
                raise StateCodecError(f"mapping keys are not canonical at {path}")
            if key in result:
                raise StateCodecError(f"duplicate mapping key at {path}: {key}")
            previous = key
            result[key] = _decode(pair[1], path=f"{path}.{key}")
        return FrozenMapping(result)
    raise StateCodecError(f"unknown state codec tag at {path}: {tag}")


def encode_state_payload(state: ModelState) -> str:
    """Encode one supported semantic state as canonical JSON text."""

    try:
        frozen = freeze_model_state(state)
        encoded = _encode(frozen, active=set(), path="$")
        return json.dumps(
            encoded,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except StateCodecError:
        raise
    except (TypeError, ValueError) as exc:
        raise StateCodecError(str(exc)) from exc


def decode_state_payload(payload: str) -> ModelState:
    """Decode and re-freeze one canonical state payload."""

    if not isinstance(payload, str):
        raise TypeError("state payload must be JSON text")
    try:
        value = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise StateCodecError("state payload must be valid JSON") from exc
    decoded = _decode(value, path="$")
    try:
        return freeze_model_state(decoded)
    except (TypeError, ValueError) as exc:
        raise StateCodecError(str(exc)) from exc


def state_payload_sha256(payload: str) -> str:
    if not isinstance(payload, str):
        raise TypeError("state payload must be JSON text")
    return sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "StateCodecError",
    "decode_state_payload",
    "encode_state_payload",
    "state_payload_sha256",
]
