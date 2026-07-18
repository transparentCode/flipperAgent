"""Canonical immutable contract for frozen historical daily source bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Any

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.domain.identity import require_utc


def _string(value: Any, *, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _timestamp(value: Any, *, field_name: str) -> datetime:
    return require_utc(value, field_name=field_name)


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
        result = 0.0
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise ContractValidationError(f"{field_name} must be at most {maximum}")
    return result


@dataclass(frozen=True)
class SourceBar:
    """One validated daily source bar from the frozen research dataset."""

    open_time: datetime
    closed_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_id: str

    def __post_init__(self) -> None:
        open_time = _timestamp(self.open_time, field_name="open_time")
        closed_at = _timestamp(self.closed_at, field_name="closed_at")
        if closed_at != open_time + timedelta(days=1):
            raise ContractValidationError("closed_at must equal open_time + 1 day")
        object.__setattr__(self, "open_time", open_time)
        object.__setattr__(self, "closed_at", closed_at)
        for field_name in ("open", "high", "low", "close"):
            value = _number(getattr(self, field_name), field_name=field_name, minimum=0.0)
            if value <= 0:
                raise ContractValidationError(f"{field_name} must be positive")
            object.__setattr__(self, field_name, value)
        if self.low > self.high or not self.low <= self.open <= self.high or not self.low <= self.close <= self.high:
            raise ContractValidationError("source OHLC values must satisfy low <= open/close <= high")
        object.__setattr__(
            self,
            "volume",
            _number(self.volume, field_name="volume", minimum=0.0),
        )
        object.__setattr__(self, "bar_id", _string(self.bar_id, field_name="bar_id"))


__all__ = ["SourceBar"]
