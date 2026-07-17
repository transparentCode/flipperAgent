"""Typed immutable configuration sections for the canonical SR model."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from libs.models.sr.domain.identity import ContractValidationError


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


@dataclass(frozen=True)
class DetectionConfig:
    """Causal candidate-detection parameters."""

    pivot_span_bars: int
    zone_half_width_atr: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "pivot_span_bars",
            _integer(
                self.pivot_span_bars,
                field_name="detection.pivot_span_bars",
                minimum=1,
            ),
        )
        object.__setattr__(
            self,
            "zone_half_width_atr",
            _number(
                self.zone_half_width_atr,
                field_name="detection.zone_half_width_atr",
                minimum=0.0,
            ),
        )


@dataclass(frozen=True)
class AssociationConfig:
    """Causal candidate-to-zone association parameters."""

    merge_distance_atr: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "merge_distance_atr",
            _number(
                self.merge_distance_atr,
                field_name="association.merge_distance_atr",
                minimum=0.0,
            ),
        )


@dataclass(frozen=True)
class LifecycleConfig:
    """Causal zone-interaction and terminal-transition parameters."""

    touch_tolerance_atr: float
    break_buffer_atr: float
    break_confirm_closes: int
    max_age_bars: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "touch_tolerance_atr",
            _number(
                self.touch_tolerance_atr,
                field_name="lifecycle.touch_tolerance_atr",
                minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "break_buffer_atr",
            _number(
                self.break_buffer_atr,
                field_name="lifecycle.break_buffer_atr",
                minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "break_confirm_closes",
            _integer(
                self.break_confirm_closes,
                field_name="lifecycle.break_confirm_closes",
                minimum=1,
            ),
        )
        object.__setattr__(
            self,
            "max_age_bars",
            _integer(
                self.max_age_bars,
                field_name="lifecycle.max_age_bars",
                minimum=1,
            ),
        )


@dataclass(frozen=True)
class RuntimeConfig:
    """Runtime limits for the stateful SR consumer."""

    max_active_zones: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_active_zones",
            _integer(
                self.max_active_zones,
                field_name="runtime.max_active_zones",
                minimum=1,
            ),
        )


__all__ = [
    "AssociationConfig",
    "DetectionConfig",
    "LifecycleConfig",
    "RuntimeConfig",
]
