"""SR zone geometry contract."""

from __future__ import annotations

from dataclasses import dataclass
import math

from ._validation import _number
from .errors import ContractValidationError


@dataclass(frozen=True)
class ZoneGeometry:
    center: float
    half_width: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "center", _number(self.center, field_name="center", minimum=0.0)
        )
        if self.center <= 0:
            raise ContractValidationError("center must be positive")
        object.__setattr__(
            self,
            "half_width",
            _number(self.half_width, field_name="half_width", minimum=0.0),
        )
        lower_bound = self.lower_bound
        upper_bound = self.upper_bound
        if not math.isfinite(lower_bound) or not math.isfinite(upper_bound):
            raise ContractValidationError("geometry bounds must be finite")
        if lower_bound <= 0:
            raise ContractValidationError("geometry lower_bound must be positive")

    @property
    def lower_bound(self) -> float:
        return self.center - self.half_width

    @property
    def upper_bound(self) -> float:
        return self.center + self.half_width


def _geometry(value: object) -> ZoneGeometry:
    if isinstance(value, ZoneGeometry):
        return value
    raise ContractValidationError("value must be ZoneGeometry")


__all__ = ["ZoneGeometry"]
