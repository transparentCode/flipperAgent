"""Canonical immutable contract for one first-touch outcome."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError, ZoneSide
from libs.models.sr.domain.identity import require_utc, utc_isoformat


def _finite(value: float, *, field_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractValidationError(f"{field_name} must be finite") from exc
    if not math.isfinite(result):
        raise ContractValidationError(f"{field_name} must be finite")
    return 0.0 if result == 0.0 else result


def _timestamp(value: datetime, *, field_name: str) -> datetime:
    return require_utc(value, field_name=field_name)


@dataclass(frozen=True)
class FirstTouchOutcome:
    zone_id: str
    side: ZoneSide
    first_touch_at: datetime
    touch_bar_id: str
    anchor_close: float
    reference_atr_14: float
    completed: bool
    right_censored: bool
    tenth_outcome_bar_closed_at: datetime | None
    favorable_reference_atr: float | None
    adverse_reference_atr: float | None
    quality_reference_atr: float | None
    invalidated: bool

    def __post_init__(self) -> None:
        if type(self.zone_id) is not str or not self.zone_id:
            raise ContractValidationError("outcome.zone_id must be a non-empty string")
        if type(self.side) is not ZoneSide:
            raise ContractValidationError("outcome.side must be exactly ZoneSide")
        object.__setattr__(self, "first_touch_at", _timestamp(self.first_touch_at, field_name="first_touch_at"))
        if type(self.touch_bar_id) is not str or not self.touch_bar_id:
            raise ContractValidationError("outcome.touch_bar_id must be a non-empty string")
        object.__setattr__(self, "anchor_close", _finite(self.anchor_close, field_name="anchor_close"))
        object.__setattr__(self, "reference_atr_14", _finite(self.reference_atr_14, field_name="reference_atr_14"))
        if self.anchor_close <= 0 or self.reference_atr_14 <= 0:
            raise ContractValidationError("outcome anchor/reference ATR must be positive")
        if type(self.completed) is not bool or type(self.right_censored) is not bool:
            raise ContractValidationError("outcome completion flags must be booleans")
        if self.completed == self.right_censored:
            raise ContractValidationError("outcome must be exactly completed or right-censored")
        tenth = self.tenth_outcome_bar_closed_at
        if tenth is not None:
            tenth = _timestamp(tenth, field_name="tenth_outcome_bar_closed_at")
        object.__setattr__(self, "tenth_outcome_bar_closed_at", tenth)
        values = (self.favorable_reference_atr, self.adverse_reference_atr, self.quality_reference_atr)
        if self.completed:
            if any(value is None for value in values) or tenth is None:
                raise ContractValidationError("completed outcome requires horizon metrics")
            normalized = tuple(_finite(value, field_name="completed outcome metric") for value in values)
            if normalized[0] < 0 or normalized[1] < 0:
                raise ContractValidationError("excursions must be non-negative")
            if abs(normalized[2] - (normalized[0] - normalized[1])) > 1e-12:
                raise ContractValidationError("quality must equal favorable minus adverse")
            object.__setattr__(self, "favorable_reference_atr", normalized[0])
            object.__setattr__(self, "adverse_reference_atr", normalized[1])
            object.__setattr__(self, "quality_reference_atr", normalized[2])
        elif any(value is not None for value in values) or self.invalidated:
            raise ContractValidationError("right-censored outcome cannot contain completed metrics")

    def to_payload(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "side": self.side.value,
            "first_touch_at": utc_isoformat(self.first_touch_at),
            "touch_bar_id": self.touch_bar_id,
            "anchor_close": self.anchor_close,
            "reference_atr_14": self.reference_atr_14,
            "completed": self.completed,
            "right_censored": self.right_censored,
            "tenth_outcome_bar_closed_at": None if self.tenth_outcome_bar_closed_at is None else utc_isoformat(self.tenth_outcome_bar_closed_at),
            "favorable_reference_atr": self.favorable_reference_atr,
            "adverse_reference_atr": self.adverse_reference_atr,
            "quality_reference_atr": self.quality_reference_atr,
            "invalidated": self.invalidated,
        }


__all__ = ["FirstTouchOutcome"]
