"""Stable public identifiers and small SR v2-owned value helpers.

The model is deliberately independent from the Decision application.  The
two tiny helpers below are kept here because they are part of the model's
closed-input/immutable-output contract; importing them from another app would
make the supposedly clean-room package depend on that app's schema.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType
from typing import Any

SR_V2_SCHEMA_VERSION = 4
SR_V2_CONFIG_VERSION = 2


def require_utc(value: object, *, field_name: str = "datetime") -> datetime:
    """Validate and return a timezone-aware UTC datetime."""

    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field_name} must use UTC")
    return value.astimezone(UTC)


def FrozenMapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a shallow immutable mapping with deterministic key order."""

    if not isinstance(value, Mapping):
        raise TypeError("FrozenMapping requires a mapping")
    if any(not isinstance(key, str) for key in value):
        raise TypeError("FrozenMapping keys must be strings")
    return MappingProxyType({key: value[key] for key in sorted(value)})


class ZoneSide(str, Enum):
    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"


class LifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    TOUCHED = "TOUCHED"
    BREAK_PENDING = "BREAK_PENDING"
    BROKEN = "BROKEN"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class ForecastOutcome(str, Enum):
    NO_TOUCH = "NO_TOUCH"
    TOUCH_THEN_BOUNCE = "TOUCH_THEN_BOUNCE"
    TOUCH_THEN_BREAK = "TOUCH_THEN_BREAK"
    TOUCH_UNRESOLVED = "TOUCH_UNRESOLVED"


__all__ = [
    "SR_V2_CONFIG_VERSION",
    "SR_V2_SCHEMA_VERSION",
    "ForecastOutcome",
    "LifecycleState",
    "ZoneSide",
]
