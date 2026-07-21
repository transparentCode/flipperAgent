"""Standard-library-only validation for immutable domain contracts."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import math
from types import MappingProxyType
from typing import Any, Mapping


class ContractValidationError(ValueError):
    """Raised when a Trendline V2 domain contract is invalid."""


def require_utc(value: datetime, *, field_name: str = "timestamp") -> datetime:
    if not isinstance(value, datetime):
        raise ContractValidationError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ContractValidationError(f"{field_name} must be timezone-aware UTC")
    return value.astimezone(timezone.utc)


def utc_isoformat(value: datetime) -> str:
    return require_utc(value).isoformat().replace("+00:00", "Z")


def parse_utc_isoformat(value: Any, *, field_name: str = "timestamp") -> datetime:
    if not isinstance(value, str):
        raise ContractValidationError(f"{field_name} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractValidationError(f"{field_name} is not ISO-8601") from exc
    return require_utc(parsed, field_name=field_name)


def require_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def require_integer(value: Any, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{field_name} must be an integer")
    if value < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    return value


def require_number(
    value: Any,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
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


def freeze_value(value: Any, *, field_name: str = "value") -> Any:
    """Recursively copy and freeze primitive metadata."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return require_number(value, field_name=field_name)
    if isinstance(value, datetime):
        return require_utc(value, field_name=field_name)
    if isinstance(value, Enum):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ContractValidationError(f"{field_name} keys must be strings")
        return MappingProxyType(
            {
                key: freeze_value(item, field_name=f"{field_name}.{key}")
                for key, item in value.items()
            }
        )
    if isinstance(value, (tuple, list)):
        return tuple(
            freeze_value(item, field_name=f"{field_name} item") for item in value
        )
    raise ContractValidationError(
        f"unsupported {field_name} value type: {type(value).__name__}"
    )


def primitive(value: Any) -> Any:
    """Convert supported domain values to canonical JSON-compatible values."""

    if isinstance(value, datetime):
        return utc_isoformat(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float):
        return require_number(value, field_name="serialized float")
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Mapping):
        return {key: primitive(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [primitive(item) for item in value]
    if is_dataclass(value):
        return {
            item.name: primitive(getattr(value, item.name))
            for item in fields(value)
            if not item.name.startswith("_")
        }
    raise ContractValidationError(
        f"unsupported canonical value type: {type(value).__name__}"
    )


__all__ = [
    "ContractValidationError",
    "freeze_value",
    "parse_utc_isoformat",
    "primitive",
    "require_integer",
    "require_number",
    "require_string",
    "require_utc",
    "utc_isoformat",
]
