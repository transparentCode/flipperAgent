"""Minimal recovery request domain contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .instrument import MarketLane


def _require_non_empty_string(value: object, *, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _require_utc(value: object, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


@dataclass(frozen=True, slots=True)
class RecoveryRequest:
    """A half-open UTC interval that should be recovered for one market lane."""

    lane: MarketLane
    since: datetime
    until: datetime
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.lane, MarketLane):
            raise TypeError("lane must be a MarketLane")
        _require_utc(self.since, field_name="since")
        _require_utc(self.until, field_name="until")
        _require_non_empty_string(self.reason, field_name="reason")
        if self.until <= self.since:
            raise ValueError("until must be after since")


__all__ = ["RecoveryRequest"]
