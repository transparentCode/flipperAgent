"""Exact timestamp-space line geometry and confirmed anchors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .validation import (
    ContractValidationError,
    _decode,
    _number,
    _primitive,
    _required,
    _string,
    parse_utc_isoformat,
    require_utc,
)

@dataclass(frozen=True)
class LineGeometry:
    reference_time: datetime
    reference_price: float
    slope_per_second: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "reference_time", require_utc(self.reference_time, field_name="reference_time"))
        object.__setattr__(self, "reference_price", _number(self.reference_price, field_name="reference_price"))
        object.__setattr__(self, "slope_per_second", _number(self.slope_per_second, field_name="slope_per_second"))

    def value_at(self, timestamp: datetime) -> float:
        return self.reference_price + self.slope_per_second * (require_utc(timestamp) - self.reference_time).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LineGeometry":
        return _decode("LineGeometry", value, lambda item: cls(
            reference_time=parse_utc_isoformat(_required(item, "reference_time", owner="LineGeometry"), field_name="reference_time"),
            reference_price=_required(item, "reference_price", owner="LineGeometry"),
            slope_per_second=_required(item, "slope_per_second", owner="LineGeometry"),
        ))


@dataclass(frozen=True)
class AnchorRef:
    anchor_id: str
    timestamp: datetime
    price: float
    pivot_kind: str
    confirmation_time: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "anchor_id", _string(self.anchor_id, field_name="anchor_id"))
        object.__setattr__(self, "pivot_kind", _string(self.pivot_kind, field_name="pivot_kind"))
        if self.pivot_kind not in {"high", "low", "unknown"}:
            raise ContractValidationError("pivot_kind must be high, low, or unknown")
        object.__setattr__(self, "timestamp", require_utc(self.timestamp, field_name="anchor timestamp"))
        object.__setattr__(self, "confirmation_time", require_utc(self.confirmation_time, field_name="confirmation_time"))
        if self.confirmation_time < self.timestamp:
            raise ContractValidationError("confirmation_time cannot precede anchor timestamp")
        object.__setattr__(self, "price", _number(self.price, field_name="anchor price"))

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnchorRef":
        return _decode("AnchorRef", value, lambda item: cls(
            anchor_id=_required(item, "anchor_id", owner="AnchorRef"),
            timestamp=parse_utc_isoformat(_required(item, "timestamp", owner="AnchorRef"), field_name="anchor timestamp"),
            price=_required(item, "price", owner="AnchorRef"),
            pivot_kind=_required(item, "pivot_kind", owner="AnchorRef"),
            confirmation_time=parse_utc_isoformat(_required(item, "confirmation_time", owner="AnchorRef"), field_name="confirmation_time"),
        ))
