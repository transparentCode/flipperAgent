"""Private primitive validation helpers for SR evaluation contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import math
import re
from typing import Any

from libs.models.sr.domain.bars import SRStateKey
from libs.models.sr.domain.errors import ContractValidationError

from .identity import normalize_utc


_HASH_RE = re.compile(r"[0-9a-f]{64}")


def _string(value: Any, *, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _hash(value: Any, *, field_name: str) -> str:
    value = _string(value, field_name=field_name)
    if _HASH_RE.fullmatch(value) is None:
        raise ContractValidationError(
            f"{field_name} must be a lowercase SHA-256 hex string"
        )
    return value


def _finite_number(
    value: Any,
    *,
    field_name: str,
    minimum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{field_name} must be finite") from exc
    if not math.isfinite(result):
        raise ContractValidationError(f"{field_name} must be finite")
    if result == 0.0:
        result = 0.0
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    return result


def _nonnegative_integer(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or type(value) is not int:
        raise ContractValidationError(f"{field_name} must be an integer")
    if value < 0:
        raise ContractValidationError(f"{field_name} must be non-negative")
    return value


def _state_key(value: Any, *, field_name: str = "state_key") -> SRStateKey:
    if type(value) is not SRStateKey:
        raise ContractValidationError(f"{field_name} must be exactly SRStateKey")
    return value


def _enum(value: Any, enum_type: type[Enum], *, field_name: str) -> Enum:
    if type(value) is not enum_type:
        raise ContractValidationError(
            f"{field_name} must be exactly {enum_type.__name__}"
        )
    return value


def _timestamp(value: Any, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ContractValidationError(f"{field_name} must be a datetime")
    return normalize_utc(value, field_name=field_name)


def _state_key_payload(state_key: SRStateKey) -> dict[str, str]:
    return {
        "venue": state_key.venue,
        "symbol": state_key.symbol,
        "timeframe": state_key.timeframe,
    }
