"""Exact timestamp-space line geometry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, Mapping

from .identity import deterministic_hash
from .validation import (
    ContractValidationError,
    parse_utc_isoformat,
    primitive,
    require_number,
    require_utc,
)


@dataclass(frozen=True, slots=True)
class LineGeometry:
    start_time: datetime
    end_time: datetime
    start_price: float
    end_price: float

    def __post_init__(self) -> None:
        start = require_utc(self.start_time, field_name="geometry.start_time")
        end = require_utc(self.end_time, field_name="geometry.end_time")
        if end <= start:
            raise ContractValidationError("geometry.end_time must be after start_time")
        start_price = require_number(
            self.start_price, field_name="geometry.start_price"
        )
        end_price = require_number(self.end_price, field_name="geometry.end_price")
        object.__setattr__(self, "start_time", start)
        object.__setattr__(self, "end_time", end)
        object.__setattr__(self, "start_price", start_price)
        object.__setattr__(self, "end_price", end_price)

    @property
    def start_seconds(self) -> float:
        return self.start_time.timestamp()

    @property
    def end_seconds(self) -> float:
        return self.end_time.timestamp()

    @property
    def slope_per_second(self) -> float:
        return (self.end_price - self.start_price) / (
            self.end_seconds - self.start_seconds
        )

    @property
    def intercept(self) -> float:
        return self.start_price - self.slope_per_second * self.start_seconds

    def value_at(self, timestamp: datetime) -> float:
        timestamp = require_utc(timestamp, field_name="geometry evaluation time")
        seconds = timestamp.timestamp()
        value = self.start_price + self.slope_per_second * (seconds - self.start_seconds)
        if not math.isfinite(value):
            raise ContractValidationError("geometry projection must be finite")
        return value

    def to_dict(self) -> dict[str, Any]:
        return primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LineGeometry":
        if not isinstance(value, Mapping):
            raise ContractValidationError("geometry payload must be a mapping")
        if set(value) != {"start_time", "end_time", "start_price", "end_price"}:
            raise ContractValidationError("geometry payload keys mismatch")
        try:
            return cls(
                start_time=parse_utc_isoformat(value["start_time"], field_name="geometry.start_time"),
                end_time=parse_utc_isoformat(value["end_time"], field_name="geometry.end_time"),
                start_price=value["start_price"],
                end_price=value["end_price"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid geometry payload") from exc

    @property
    def geometry_id(self) -> str:
        return deterministic_hash("trendline_v2_geometry", self.to_dict())


__all__ = ["LineGeometry"]
