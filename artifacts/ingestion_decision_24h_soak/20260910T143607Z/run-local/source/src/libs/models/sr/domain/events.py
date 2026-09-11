"""SR lifecycle-event contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ._validation import _hash, _number, _string
from .errors import ContractValidationError
from .identity import hash_event, require_utc


class SREventType(str, Enum):
    CREATED = "CREATED"
    TOUCHED = "TOUCHED"
    BREACH_STARTED = "BREACH_STARTED"
    FALSE_BREAKOUT = "FALSE_BREAKOUT"
    BREAK_CONFIRMED = "BREAK_CONFIRMED"
    EXPIRED = "EXPIRED"


def _event_type(value: object) -> SREventType:
    try:
        return value if isinstance(value, SREventType) else SREventType(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid SR event type: {value!r}") from exc


@dataclass(frozen=True)
class SREvent:
    zone_id: str
    event_type: SREventType
    timestamp: datetime
    price: float
    bar_id: str
    event_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "zone_id", _hash(self.zone_id, field_name="zone_id"))
        object.__setattr__(self, "event_type", _event_type(self.event_type))
        object.__setattr__(
            self, "timestamp", require_utc(self.timestamp, field_name="timestamp")
        )
        object.__setattr__(
            self, "price", _number(self.price, field_name="price", minimum=0.0)
        )
        if self.price <= 0:
            raise ContractValidationError("price must be positive")
        object.__setattr__(self, "bar_id", _string(self.bar_id, field_name="bar_id"))
        object.__setattr__(self, "event_id", hash_event(self))


__all__ = ["SREvent", "SREventType"]
