"""Primitive validation and immutable-value helpers for trendline contracts."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import math
import re
from types import MappingProxyType
from typing import Any, Callable, Mapping, TypeVar

class ContractValidationError(ValueError):
    """Raised when a trendline-family contract is unsafe or invalid."""
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_T = TypeVar("_T")

# A deterministic tolerance for values produced by timestamp-space line
# projection and independently serialized audit fields.
_INTERACTION_FLOAT_TOLERANCE = 1e-9

_PHASE_G_DIAGNOSTIC_KEYS = frozenset(
    {
        "rail_group_count",
        "rail_grouping_rejection_reasons",
        "family_corridor_count",
        "singleton_family_count",
        "multi_rail_family_count",
        "total_rail_count",
        "representative_change_count",
    }
)


def _interaction_close(left: float, right: float) -> bool:
    """Compare persisted interaction audit values without changing their value."""

    return math.isclose(
        left,
        right,
        rel_tol=1e-12,
        abs_tol=_INTERACTION_FLOAT_TOLERANCE,
    )


def require_utc(timestamp: datetime, *, field_name: str = "timestamp") -> datetime:
    """Reject naive and non-UTC timestamps instead of silently changing geometry."""

    if not isinstance(timestamp, datetime):
        raise ContractValidationError(f"{field_name} must be a datetime")
    if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
        raise ContractValidationError(f"{field_name} must be timezone-aware UTC")
    return timestamp.astimezone(timezone.utc)


def utc_isoformat(timestamp: datetime) -> str:
    return require_utc(timestamp).isoformat().replace("+00:00", "Z")


def parse_utc_isoformat(value: Any, *, field_name: str = "timestamp") -> datetime:
    if not isinstance(value, str):
        raise ContractValidationError(f"{field_name} must be an ISO-8601 string")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractValidationError(f"{field_name} is not ISO-8601") from exc
    return require_utc(timestamp, field_name=field_name)


def _string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: Any, *, field_name: str) -> str | None:
    return None if value is None else _string(value, field_name=field_name)


def _integer(value: Any, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{field_name} must be an integer")
    if value < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    return value


def _optional_integer(value: Any, *, field_name: str, minimum: int = 0) -> int | None:
    return None if value is None else _integer(value, field_name=field_name, minimum=minimum)


def _number(value: Any, *, field_name: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ContractValidationError(f"{field_name} must be finite")
    if minimum is not None and number < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    if maximum is not None and number > maximum:
        raise ContractValidationError(f"{field_name} must be at most {maximum}")
    return number


def _optional_number(value: Any, *, field_name: str, minimum: float | None = None, maximum: float | None = None) -> float | None:
    return None if value is None else _number(value, field_name=field_name, minimum=minimum, maximum=maximum)


def _mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ContractValidationError(f"{field_name} must be a mapping with string keys")
    return value


def _required(value: Mapping[str, Any], key: str, *, owner: str) -> Any:
    if key not in value:
        raise ContractValidationError(f"{owner} missing required field: {key}")
    return value[key]


def _tuple_of_strings(value: Any, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise ContractValidationError(f"{field_name} must be a sequence")
    return tuple(_string(item, field_name=f"{field_name} item") for item in value)


def _freeze_value(value: Any, *, field_name: str) -> Any:
    """Recursively copy immutable metadata so published contracts cannot mutate."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return _number(value, field_name=field_name)
    if isinstance(value, datetime):
        return require_utc(value, field_name=field_name)
    if isinstance(value, Enum):
        return value
    if isinstance(value, Mapping):
        mapping = _mapping(value, field_name=field_name)
        return MappingProxyType({key: _freeze_value(item, field_name=f"{field_name}.{key}") for key, item in mapping.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_value(item, field_name=f"{field_name} item") for item in value)
    raise ContractValidationError(f"unsupported {field_name} value type: {type(value)!r}")


def _freeze_mapping(value: Mapping[str, Any] | None, *, field_name: str) -> Mapping[str, Any]:
    return _freeze_value(value or {}, field_name=field_name)


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
        return {item.name: _primitive(getattr(value, item.name)) for item in fields(value)}
    raise ContractValidationError(f"unsupported canonical value type: {type(value)!r}")
def _hash(value: Any, *, field_name: str) -> str:
    text = _string(value, field_name=field_name)
    if _HASH_PATTERN.fullmatch(text) is None:
        raise ContractValidationError(f"{field_name} must be a lowercase SHA-256 hex string")
    return text


def _decode(owner: str, value: Any, build: Callable[[Mapping[str, Any]], _T]) -> _T:
    mapping = _mapping(value, field_name=owner)
    try:
        return build(mapping)
    except ContractValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid {owner} payload") from exc
