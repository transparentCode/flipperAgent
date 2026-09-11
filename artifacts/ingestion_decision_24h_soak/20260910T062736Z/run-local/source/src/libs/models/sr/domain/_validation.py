"""Private primitive validation helpers shared by SR domain contracts."""

from __future__ import annotations

import math
import re
from typing import Any

from .errors import ContractValidationError


def _string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _integer(value: Any, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{field_name} must be an integer")
    if value < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    return value


def _number(
    value: Any,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
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
        return 0.0
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise ContractValidationError(f"{field_name} must be at most {maximum}")
    return result


def _hash(value: Any, *, field_name: str) -> str:
    text = _string(value, field_name=field_name)
    if re.fullmatch(r"[0-9a-f]{64}", text) is None:
        raise ContractValidationError(
            f"{field_name} must be a lowercase SHA-256 hex string"
        )
    return text


def _tuple_of(
    value: Any,
    item_type: type,
    *,
    field_name: str,
) -> tuple[Any, ...]:
    if isinstance(value, (list, tuple)):
        seq = value
    else:
        raise ContractValidationError(
            f"{field_name} must be a list or tuple of {item_type.__name__}"
        )
    for idx, item in enumerate(seq):
        if not isinstance(item, item_type):
            raise ContractValidationError(
                f"{field_name}[{idx}] must be {item_type.__name__}"
            )
    return tuple(seq)
