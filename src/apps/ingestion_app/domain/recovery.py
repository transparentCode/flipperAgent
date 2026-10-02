"""Minimal recovery request domain contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .instrument import MarketLane
from .validation import require_non_empty_string, require_utc


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
        require_utc(self.since, field_name="since")
        require_utc(self.until, field_name="until")
        require_non_empty_string(self.reason, field_name="reason")
        if self.until <= self.since:
            raise ValueError("until must be after since")


__all__ = ["RecoveryRequest"]
