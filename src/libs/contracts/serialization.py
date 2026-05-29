"""Valkey serialization utilities for Pydantic models."""

import json as _json
from enum import Enum
from typing import Any, TypeVar, Union

from pydantic import BaseModel

_T = TypeVar("_T", bound=BaseModel)

# Sentinel for None values in Valkey flat-map payloads
_NONE_SENTINEL = "__NONE__"


def valkey_encode(model: BaseModel, *, inject_trace: bool = True) -> dict[str, str]:
    """Serialize a Pydantic model to a flat dict[str, str] suitable for Valkey XADD.

    Rules:
    - None values → sentinel string "__NONE__"
    - dict/list values → JSON string
    - Enum values → their .value
    - Everything else → str()

    If inject_trace=True (default), injects W3C traceparent into the payload.
    """
    payload: dict[str, str] = {}
    for key, value in model.model_dump().items():
        if value is None:
            payload[key] = _NONE_SENTINEL
        elif isinstance(value, Enum):
            payload[key] = str(value.value)
        elif isinstance(value, (dict, list)):
            payload[key] = _json.dumps(value)
        else:
            payload[key] = str(value)

    if inject_trace:
        try:
            from libs.common.telemetry.propagation import inject_trace_context
            inject_trace_context(payload)
        except ImportError:
            pass  # OTel not installed — graceful degradation

    return payload


def valkey_decode(payload: dict[str, str], model_class: type[_T]) -> _T:
    """Deserialize a Valkey flat-map payload back into a Pydantic model.

    Reverses valkey_encode:
    - "__NONE__" sentinel → None
    - JSON strings for dict/list fields → parsed
    - Pydantic handles type coercion for numeric fields
    """
    # Coerce any bytes keys/values to str (safety net for mixed clients)
    coerced: dict[str, str] = {}
    for k, v in payload.items():
        key = k.decode("utf-8") if isinstance(k, bytes) else k
        val = v.decode("utf-8") if isinstance(v, bytes) else v
        coerced[key] = val
    fields = model_class.model_fields
    parsed: dict[str, Any] = {}
    for key, raw_value in coerced.items():
        if key not in fields:
            parsed[key] = raw_value
            continue
        if raw_value == _NONE_SENTINEL or raw_value == "None":
            parsed[key] = None
            continue
        field_annotation = fields[key].annotation
        # Unwrap Optional[X] → X
        origin = getattr(field_annotation, "__origin__", None)
        if origin is Union:
            args = [a for a in field_annotation.__args__ if a is not type(None)]
            field_annotation = args[0] if args else field_annotation
        if field_annotation in (dict, list) or getattr(field_annotation, "__origin__", None) in (dict, list):
            try:
                parsed[key] = _json.loads(raw_value)
            except (ValueError, TypeError):
                parsed[key] = raw_value
        else:
            parsed[key] = raw_value
    return model_class.model_validate(parsed)


__all__ = ["valkey_encode", "valkey_decode", "_NONE_SENTINEL", "_T"]
