"""Strict schema and safety bounds for SR v2 configuration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from math import isfinite
from typing import Any


class SRV2ConfigError(ValueError):
    """Raised for invalid or non-canonical SR v2 configuration."""


TIMEFRAME_DURATIONS = {
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "6h": timedelta(hours=6),
    "1d": timedelta(days=1),
}
# This is a capability ontology, not a runtime ladder.  The selected ladder
# and its order belong exclusively to the model YAML.
SUPPORTED_TIMEFRAMES = tuple(
    sorted(TIMEFRAME_DURATIONS, key=TIMEFRAME_DURATIONS.__getitem__, reverse=True)
)
MAX_HORIZONS = 8
MAX_HORIZON = timedelta(days=365)
MAX_EXPIRY = timedelta(days=730)


def require_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SRV2ConfigError(f"{name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise SRV2ConfigError(f"{name} keys must be strings")
    return value


def require_exact_keys(mapping: Mapping[str, Any], required: set[str], name: str) -> None:
    unknown = sorted(set(mapping) - required)
    missing = sorted(required - set(mapping))
    if unknown:
        raise SRV2ConfigError(f"unknown {name} keys: {', '.join(unknown)}")
    if missing:
        raise SRV2ConfigError(f"missing {name} keys: {', '.join(missing)}")


def bounded_int(value: object, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SRV2ConfigError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise SRV2ConfigError(f"{name} must be in [{minimum}, {maximum}]")
    return value


def positive_int(value: object, name: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int):
        raise SRV2ConfigError(f"{name} must be an integer")
    if value < minimum:
        raise SRV2ConfigError(f"{name} must be positive")
    return value


def bounded_decimal(value: object, name: str, *, maximum: Decimal) -> Decimal:
    result = positive_decimal(value, name)
    if result > maximum:
        raise SRV2ConfigError(f"{name} must be <= {maximum}")
    return result


def positive_decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise SRV2ConfigError(f"{name} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SRV2ConfigError(f"{name} must be numeric") from exc
    if not result.is_finite() or result <= 0:
        raise SRV2ConfigError(f"{name} must be finite and positive")
    return result


def finite_probability(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SRV2ConfigError(f"{name} must be numeric")
    result = float(value)
    if not isfinite(result) or not 0 <= result <= 1:
        raise SRV2ConfigError(f"{name} must be finite and in [0, 1]")
    return result


def duration(value: object, name: str) -> timedelta:
    if not isinstance(value, str) or not value.strip():
        raise SRV2ConfigError(f"{name} must be a duration string")
    text = value.strip().lower()
    for suffix, seconds in (("d", 86400), ("h", 3600), ("m", 60)):
        if text.endswith(suffix):
            try:
                amount = Decimal(text[: -len(suffix)])
            except (InvalidOperation, ValueError) as exc:
                raise SRV2ConfigError(f"invalid {name}: {value}") from exc
            if not amount.is_finite() or amount <= 0:
                raise SRV2ConfigError(f"{name} must be positive")
            micros = int(amount * seconds * 1_000_000)
            if Decimal(micros) != amount * seconds * 1_000_000:
                raise SRV2ConfigError(f"{name} must resolve to whole microseconds")
            return timedelta(microseconds=micros)
    raise SRV2ConfigError(f"unsupported {name} duration: {value}")


def validate_ladder(value: object, name: str = "runtime.ladder") -> tuple[str, ...]:
    """Resolve a strict descending, supported SR v2 timeframe ladder."""

    if not isinstance(value, (list, tuple)) or isinstance(value, (str, bytes)):
        raise SRV2ConfigError(f"{name} must be a sequence")
    ladder = tuple(value)
    if not ladder:
        raise SRV2ConfigError(f"{name} must not be empty")
    if any(not isinstance(item, str) or not item.strip() for item in ladder):
        raise SRV2ConfigError(f"{name} must contain non-empty timeframe strings")
    if len(set(ladder)) != len(ladder):
        raise SRV2ConfigError(f"{name} must contain unique timeframes")
    unsupported = sorted(set(ladder) - set(SUPPORTED_TIMEFRAMES))
    if unsupported:
        raise SRV2ConfigError(f"{name} contains unsupported timeframes: {', '.join(unsupported)}")
    if any(
        TIMEFRAME_DURATIONS[left] <= TIMEFRAME_DURATIONS[right]
        for left, right in pairwise(ladder)
    ):
        raise SRV2ConfigError(f"{name} must be ordered by strictly descending duration")
    return ladder


__all__ = [
    "MAX_EXPIRY",
    "MAX_HORIZON",
    "MAX_HORIZONS",
    "SUPPORTED_TIMEFRAMES",
    "TIMEFRAME_DURATIONS",
    "SRV2ConfigError",
    "bounded_decimal",
    "bounded_int",
    "duration",
    "finite_probability",
    "positive_decimal",
    "positive_int",
    "require_exact_keys",
    "require_mapping",
    "validate_ladder",
]
