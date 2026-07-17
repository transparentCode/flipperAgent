"""Canonical immutable contract for cohort evaluation folds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import require_utc, utc_isoformat


def _string(value: Any, *, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _timestamp(value: Any, *, field_name: str) -> datetime:
    try:
        result = require_utc(value, field_name=field_name)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{field_name} must be a UTC-aware timestamp") from exc
    return result


@dataclass(frozen=True)
class CohortFold:
    """One half-open UTC development fold."""

    name: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _string(self.name, field_name="fold.name"))
        start = _timestamp(self.start, field_name="fold.start")
        end = _timestamp(self.end, field_name="fold.end")
        if start >= end:
            raise ContractValidationError("fold.start must be before fold.end")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    def to_payload(self) -> dict[str, Any]:
        return {"name": self.name, "start": utc_isoformat(self.start), "end": utc_isoformat(self.end)}


__all__ = ["CohortFold"]
