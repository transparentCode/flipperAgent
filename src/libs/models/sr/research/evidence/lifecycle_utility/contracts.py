"""Immutable contracts for the SR-V1.11 lifecycle utility."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import math
import re
from typing import Any

from libs.models.sr.domain import ContractValidationError, ZoneSide
from libs.models.sr.domain.identity import deterministic_hash, require_utc, utc_isoformat

from .config import (
    FROZEN_EVENT_CLASSES,
    FROZEN_FOLD_NAMES,
    FROZEN_SOURCE_BUNDLE_ID,
    FROZEN_SOURCE_ID,
    FROZEN_BARS_SHA256,
    V10_AUDIT_ID,
    V10_BUNDLE_ID,
    V19_BUNDLE_ID,
    V19_STUDY_ID,
)


SCHEMA_VERSION = "1.0"
DISPOSITION_VALUES = (
    "INVALID_EVIDENCE",
    "INSUFFICIENT_EVIDENCE",
    "LIFECYCLE_CONTEXT_SUPPORTED",
    "LIFECYCLE_CONTEXT_NOT_SUPPORTED",
)
_GATE_NAMES = (
    "readiness.completed_unique_resolutions",
    "readiness.comparable_folds",
    "readiness.minimum_completed_per_comparable_fold",
    "readiness.minimum_null_controls_per_compared_cell",
    "quality.pooled_median_excess_quality_atr",
    "quality.positive_comparable_fold_fraction",
    "quality.worst_comparable_fold_median_excess_atr",
    "stability.false_breakout_median_excess_quality_atr",
    "stability.break_confirmed_median_excess_quality_atr",
)
_GATE_SPECS: dict[str, tuple[str, str, float | int, str]] = {
    "readiness.completed_unique_resolutions": ("readiness", ">=", 16, "integer"),
    "readiness.comparable_folds": ("readiness", ">=", 4, "integer"),
    "readiness.minimum_completed_per_comparable_fold": ("readiness", ">=", 2, "integer"),
    "readiness.minimum_null_controls_per_compared_cell": ("readiness", ">=", 4, "integer"),
    "quality.pooled_median_excess_quality_atr": ("quality", ">=", 0.10, "number"),
    "quality.positive_comparable_fold_fraction": ("quality", ">=", 0.60, "number"),
    "quality.worst_comparable_fold_median_excess_atr": ("quality", ">=", -0.10, "number"),
    "stability.false_breakout_median_excess_quality_atr": ("stability", ">=", 0.0, "number"),
    "stability.break_confirmed_median_excess_quality_atr": ("stability", ">=", 0.0, "number"),
}
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")


def _string(value: Any, *, path: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{path} must be a non-empty string")
    return value


def _hash(value: Any, *, path: str) -> str:
    value = _string(value, path=path)
    if _HASH_RE.fullmatch(value) is None:
        raise ContractValidationError(f"{path} must be a lowercase SHA-256 hex string")
    return value


def _commit(value: Any, *, path: str) -> str:
    value = _string(value, path=path)
    if _COMMIT_RE.fullmatch(value) is None:
        raise ContractValidationError(f"{path} must be a git SHA")
    return value


def _number(value: Any, *, path: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{path} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{path} must be finite") from exc
    if not math.isfinite(result):
        raise ContractValidationError(f"{path} must be finite")
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{path} must be >= {minimum}")
    return 0.0 if result == 0.0 else result


def _integer(value: Any, *, path: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or type(value) is not int or value < minimum:
        raise ContractValidationError(f"{path} must be an integer >= {minimum}")
    return value


def _timestamp(value: Any, *, path: str) -> datetime:
    try:
        return require_utc(value, field_name=path)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{path} must be UTC-aware") from exc


def _side(value: Any, *, path: str) -> ZoneSide:
    if type(value) is not ZoneSide:
        raise ContractValidationError(f"{path} must be exactly ZoneSide")
    return value


def _op(value: int | float, threshold: int | float, operator: str) -> bool:
    if operator == ">=":
        return value >= threshold
    raise ContractValidationError("unsupported lifecycle utility gate operator")


def flipped_side(side: ZoneSide) -> ZoneSide:
    side = _side(side, path="side")
    return ZoneSide.RESISTANCE if side is ZoneSide.SUPPORT else ZoneSide.SUPPORT


def effective_side_for_event(event_class: str, original_side: ZoneSide) -> ZoneSide:
    event_class = _string(event_class, path="event_class")
    original_side = _side(original_side, path="original_side")
    if event_class == "FALSE_BREAKOUT":
        return original_side
    if event_class == "BREAK_CONFIRMED":
        return flipped_side(original_side)
    raise ContractValidationError("unsupported lifecycle resolution event class")


@dataclass(frozen=True)
class ResolutionEvent:
    case_id: str
    zone_id: str
    event_id: str
    event_class: str
    event_at: datetime
    event_bar_id: str
    event_fold: str
    original_side: ZoneSide
    effective_side: ZoneSide
    anchor_close: float
    atr_at_event: float
    atr_at_creation: float
    center: float
    lower_bound: float
    upper_bound: float
    resolution_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("case_id", "zone_id", "event_id"):
            object.__setattr__(self, name, _hash(getattr(self, name), path=f"resolution.{name}"))
        object.__setattr__(self, "event_class", _string(self.event_class, path="resolution.event_class"))
        if self.event_class not in FROZEN_EVENT_CLASSES:
            raise ContractValidationError("resolution event class is not approved")
        object.__setattr__(self, "event_at", _timestamp(self.event_at, path="resolution.event_at"))
        object.__setattr__(self, "event_bar_id", _string(self.event_bar_id, path="resolution.event_bar_id"))
        object.__setattr__(self, "event_fold", _string(self.event_fold, path="resolution.event_fold"))
        if self.event_fold not in FROZEN_FOLD_NAMES:
            raise ContractValidationError("resolution event fold is not approved")
        object.__setattr__(self, "original_side", _side(self.original_side, path="resolution.original_side"))
        object.__setattr__(self, "effective_side", _side(self.effective_side, path="resolution.effective_side"))
        if self.effective_side is not effective_side_for_event(self.event_class, self.original_side):
            raise ContractValidationError("resolution effective side does not match event class")
        for name in ("anchor_close", "atr_at_event", "atr_at_creation"):
            object.__setattr__(self, name, _number(getattr(self, name), path=f"resolution.{name}", minimum=0.0))
            if getattr(self, name) <= 0:
                raise ContractValidationError(f"resolution.{name} must be positive")
        for name in ("lower_bound", "center", "upper_bound"):
            object.__setattr__(self, name, _number(getattr(self, name), path=f"resolution.{name}", minimum=0.0))
        if not self.lower_bound <= self.center <= self.upper_bound:
            raise ContractValidationError("resolution zone bounds do not reconcile")
        object.__setattr__(self, "resolution_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "case_id": self.case_id,
            "zone_id": self.zone_id,
            "event_id": self.event_id,
            "event_class": self.event_class,
            "event_at": utc_isoformat(self.event_at),
            "event_bar_id": self.event_bar_id,
            "event_fold": self.event_fold,
            "original_side": self.original_side.value,
            "effective_side": self.effective_side.value,
            "anchor_close": self.anchor_close,
            "atr_at_event": self.atr_at_event,
            "atr_at_creation": self.atr_at_creation,
            "center": self.center,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "resolution_id": self.resolution_id}


@dataclass(frozen=True)
class NullCell:
    fold: str
    effective_side: ZoneSide
    control_count: int
    median_quality_atr: float | None
    control_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "fold", _string(self.fold, path="null.fold"))
        if self.fold not in FROZEN_FOLD_NAMES:
            raise ContractValidationError("null fold is not approved")
        object.__setattr__(self, "effective_side", _side(self.effective_side, path="null.effective_side"))
        object.__setattr__(self, "control_count", _integer(self.control_count, path="null.control_count"))
        if type(self.control_ids) is not tuple or any(type(item) is not str or not item for item in self.control_ids) or len(self.control_ids) != self.control_count or len(set(self.control_ids)) != len(self.control_ids):
            raise ContractValidationError("null control IDs do not reconcile")
        if self.median_quality_atr is not None:
            object.__setattr__(self, "median_quality_atr", _number(self.median_quality_atr, path="null.median_quality_atr"))
        if (self.control_count == 0) != (self.median_quality_atr is None):
            raise ContractValidationError("null median/count do not reconcile")

    def to_payload(self) -> dict[str, Any]:
        return {"fold": self.fold, "effective_side": self.effective_side.value, "control_count": self.control_count, "median_quality_atr": self.median_quality_atr, "control_ids": list(self.control_ids)}


@dataclass(frozen=True)
class ResolutionOutcome:
    resolution_id: str
    zone_id: str
    case_id: str
    event_id: str
    event_class: str
    event_at: datetime
    event_bar_id: str
    event_fold: str
    original_side: ZoneSide
    effective_side: ZoneSide
    anchor_close: float
    reference_atr_14: float
    outcome_start_bar_id: str
    outcome_end_at: datetime | None
    completed: bool
    right_censored: bool
    favorable_excursion_atr: float | None
    adverse_excursion_atr: float | None
    directional_quality_atr: float | None
    null_median_quality_atr: float | None
    excess_quality_atr: float | None
    null_control_count: int
    outcome_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("resolution_id", "zone_id", "case_id", "event_id"):
            object.__setattr__(self, name, _hash(getattr(self, name), path=f"outcome.{name}"))
        object.__setattr__(self, "event_class", _string(self.event_class, path="outcome.event_class"))
        if self.event_class not in FROZEN_EVENT_CLASSES:
            raise ContractValidationError("outcome event class is not approved")
        object.__setattr__(self, "event_at", _timestamp(self.event_at, path="outcome.event_at"))
        object.__setattr__(self, "event_bar_id", _string(self.event_bar_id, path="outcome.event_bar_id"))
        object.__setattr__(self, "event_fold", _string(self.event_fold, path="outcome.event_fold"))
        if self.event_fold not in FROZEN_FOLD_NAMES:
            raise ContractValidationError("outcome event fold is not approved")
        object.__setattr__(self, "original_side", _side(self.original_side, path="outcome.original_side"))
        object.__setattr__(self, "effective_side", _side(self.effective_side, path="outcome.effective_side"))
        if self.effective_side is not effective_side_for_event(self.event_class, self.original_side):
            raise ContractValidationError("outcome effective side does not match event class")
        object.__setattr__(self, "anchor_close", _number(self.anchor_close, path="outcome.anchor_close", minimum=0.0))
        object.__setattr__(self, "reference_atr_14", _number(self.reference_atr_14, path="outcome.reference_atr_14", minimum=0.0))
        if self.anchor_close <= 0 or self.reference_atr_14 <= 0:
            raise ContractValidationError("outcome anchor/reference ATR must be positive")
        object.__setattr__(self, "outcome_start_bar_id", _string(self.outcome_start_bar_id, path="outcome.outcome_start_bar_id"))
        if self.outcome_end_at is not None:
            object.__setattr__(self, "outcome_end_at", _timestamp(self.outcome_end_at, path="outcome.outcome_end_at"))
        if type(self.completed) is not bool or type(self.right_censored) is not bool or self.completed == self.right_censored:
            raise ContractValidationError("outcome must be exactly completed or right-censored")
        object.__setattr__(self, "null_control_count", _integer(self.null_control_count, path="outcome.null_control_count"))
        values = (self.favorable_excursion_atr, self.adverse_excursion_atr, self.directional_quality_atr)
        if self.completed:
            if self.outcome_end_at is None or any(value is None for value in values):
                raise ContractValidationError("completed outcome requires horizon metrics")
            normalized = tuple(_number(value, path="outcome.metric", minimum=0.0 if index < 2 else None) for index, value in enumerate(values))
            if abs(normalized[2] - (normalized[0] - normalized[1])) > 1e-12:
                raise ContractValidationError("outcome quality formula mismatch")
            object.__setattr__(self, "favorable_excursion_atr", normalized[0])
            object.__setattr__(self, "adverse_excursion_atr", normalized[1])
            object.__setattr__(self, "directional_quality_atr", normalized[2])
            if self.null_median_quality_atr is not None:
                object.__setattr__(self, "null_median_quality_atr", _number(self.null_median_quality_atr, path="outcome.null_median_quality_atr"))
            if (self.null_control_count == 0) != (self.null_median_quality_atr is None):
                raise ContractValidationError("outcome null count/median do not reconcile")
            if self.excess_quality_atr is not None:
                if self.null_median_quality_atr is None:
                    raise ContractValidationError("outcome excess requires a null median")
                object.__setattr__(self, "excess_quality_atr", _number(self.excess_quality_atr, path="outcome.excess_quality_atr"))
                if abs(self.excess_quality_atr - (self.directional_quality_atr - self.null_median_quality_atr)) > 1e-12:
                    raise ContractValidationError("outcome excess formula mismatch")
        else:
            if self.outcome_end_at is not None or any(value is not None for value in values) or self.null_median_quality_atr is not None or self.excess_quality_atr is not None or self.null_control_count != 0:
                raise ContractValidationError("right-censored outcome cannot contain imputed metrics")
        if self.completed and self.outcome_end_at <= self.event_at:
            raise ContractValidationError("completed outcome horizon must be after its resolution event")

        object.__setattr__(self, "outcome_id", deterministic_hash(self.identity_payload()))

    @property
    def compared(self) -> bool:
        return self.completed and self.excess_quality_atr is not None

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "resolution_id": self.resolution_id,
            "zone_id": self.zone_id,
            "case_id": self.case_id,
            "event_id": self.event_id,
            "event_class": self.event_class,
            "event_at": utc_isoformat(self.event_at),
            "event_bar_id": self.event_bar_id,
            "event_fold": self.event_fold,
            "original_side": self.original_side.value,
            "effective_side": self.effective_side.value,
            "anchor_close": self.anchor_close,
            "reference_atr_14": self.reference_atr_14,
            "outcome_start_bar_id": self.outcome_start_bar_id,
            "outcome_end_at": None if self.outcome_end_at is None else utc_isoformat(self.outcome_end_at),
            "completed": self.completed,
            "right_censored": self.right_censored,
            "favorable_excursion_atr": self.favorable_excursion_atr,
            "adverse_excursion_atr": self.adverse_excursion_atr,
            "directional_quality_atr": self.directional_quality_atr,
            "null_median_quality_atr": self.null_median_quality_atr,
            "excess_quality_atr": self.excess_quality_atr,
            "null_control_count": self.null_control_count,
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "outcome_id": self.outcome_id}


@dataclass(frozen=True)
class EventClassMetrics:
    event_class: str
    comparable_outcome_count: int
    median_excess_quality_atr: float | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_class", _string(self.event_class, path="event_class_metrics.event_class"))
        if self.event_class not in FROZEN_EVENT_CLASSES:
            raise ContractValidationError("event class metrics contain an unknown class")
        object.__setattr__(self, "comparable_outcome_count", _integer(self.comparable_outcome_count, path="event_class_metrics.count"))
        if self.median_excess_quality_atr is not None:
            object.__setattr__(self, "median_excess_quality_atr", _number(self.median_excess_quality_atr, path="event_class_metrics.median"))
        if (self.comparable_outcome_count == 0) != (self.median_excess_quality_atr is None):
            raise ContractValidationError("event class metric count/median do not reconcile")

    def to_payload(self) -> dict[str, Any]:
        return {"event_class": self.event_class, "comparable_outcome_count": self.comparable_outcome_count, "median_excess_quality_atr": self.median_excess_quality_atr}


@dataclass(frozen=True)
class FoldMetrics:
    fold: str
    total_resolution_count: int
    completed_count: int
    right_censored_count: int
    compared_count: int
    minimum_null_control_count: int | None
    comparable: bool
    median_excess_quality_atr: float | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "fold", _string(self.fold, path="fold_metrics.fold"))
        if self.fold not in FROZEN_FOLD_NAMES:
            raise ContractValidationError("fold metric name is not approved")
        for name in ("total_resolution_count", "completed_count", "right_censored_count", "compared_count"):
            object.__setattr__(self, name, _integer(getattr(self, name), path=f"fold_metrics.{name}"))
        if self.completed_count + self.right_censored_count != self.total_resolution_count:
            raise ContractValidationError("fold outcome counts do not reconcile")
        if self.minimum_null_control_count is not None:
            object.__setattr__(self, "minimum_null_control_count", _integer(self.minimum_null_control_count, path="fold_metrics.minimum_null_control_count"))
        if self.median_excess_quality_atr is not None:
            object.__setattr__(self, "median_excess_quality_atr", _number(self.median_excess_quality_atr, path="fold_metrics.median_excess_quality_atr"))
        if self.comparable:
            if self.completed_count < 2 or self.minimum_null_control_count is None or self.minimum_null_control_count < 4 or self.compared_count != self.completed_count:
                raise ContractValidationError("comparable fold violates lifecycle utility gates")
            if self.median_excess_quality_atr is None:
                raise ContractValidationError("comparable fold lacks a median excess")
        elif self.compared_count or self.median_excess_quality_atr is not None:
            raise ContractValidationError("non-comparable fold cannot carry comparable metrics")

    def to_payload(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class AggregateMetrics:
    total_resolution_count: int
    completed_count: int
    right_censored_count: int
    compared_count: int
    comparable_fold_count: int
    pooled_median_excess_quality_atr: float | None
    positive_comparable_fold_fraction: float | None
    worst_comparable_fold_median_excess_atr: float | None
    event_classes: tuple[EventClassMetrics, ...]

    def __post_init__(self) -> None:
        for name in ("total_resolution_count", "completed_count", "right_censored_count", "compared_count", "comparable_fold_count"):
            object.__setattr__(self, name, _integer(getattr(self, name), path=f"aggregate.{name}"))
        if self.completed_count + self.right_censored_count != self.total_resolution_count:
            raise ContractValidationError("aggregate outcome counts do not reconcile")
        if self.compared_count > self.completed_count:
            raise ContractValidationError("aggregate compared count exceeds completed count")
        for name in ("pooled_median_excess_quality_atr", "positive_comparable_fold_fraction", "worst_comparable_fold_median_excess_atr"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _number(value, path=f"aggregate.{name}"))
        if self.positive_comparable_fold_fraction is not None and not 0.0 <= self.positive_comparable_fold_fraction <= 1.0:
            raise ContractValidationError("aggregate positive fold fraction must be in [0, 1]")
        if type(self.event_classes) is not tuple or tuple(item.event_class for item in self.event_classes) != FROZEN_EVENT_CLASSES:
            raise ContractValidationError("aggregate event-class metrics are incomplete or unordered")
        if self.comparable_fold_count == 0:
            if self.compared_count or any(getattr(self, name) is not None for name in ("pooled_median_excess_quality_atr", "positive_comparable_fold_fraction", "worst_comparable_fold_median_excess_atr")):
                raise ContractValidationError("undefined aggregate metrics were populated")
        elif any(getattr(self, name) is None for name in ("pooled_median_excess_quality_atr", "positive_comparable_fold_fraction", "worst_comparable_fold_median_excess_atr")):
            raise ContractValidationError("comparable aggregate metrics are incomplete")
        if sum(item.comparable_outcome_count for item in self.event_classes) != self.compared_count:
            raise ContractValidationError("aggregate event-class counts do not reconcile")

    def to_payload(self) -> dict[str, Any]:
        return {name: [item.to_payload() for item in value] if name == "event_classes" else value for name, value in ((name, getattr(self, name)) for name in self.__dataclass_fields__)}


@dataclass(frozen=True)
class GateResult:
    name: str
    category: str
    passed: bool
    applicable: bool
    value: int | float | None
    threshold: int | float
    operator: str
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _string(self.name, path="gate.name"))
        if self.name not in _GATE_SPECS:
            raise ContractValidationError("unknown lifecycle utility gate name")
        expected_category, expected_operator, expected_threshold, value_kind = _GATE_SPECS[self.name]
        if _string(self.category, path="gate.category") != expected_category or self.operator != expected_operator:
            raise ContractValidationError("lifecycle utility gate category/operator mismatch")
        if type(self.applicable) is not bool or type(self.passed) is not bool or type(self.reason) is not str or not self.reason:
            raise ContractValidationError("lifecycle utility gate flags/reason are invalid")
        threshold = _number(self.threshold, path="gate.threshold")
        if threshold != float(expected_threshold):
            raise ContractValidationError("lifecycle utility gate threshold is not approved")
        object.__setattr__(self, "threshold", int(threshold) if value_kind == "integer" else threshold)
        if value_kind == "integer":
            if self.value is not None and (isinstance(self.value, bool) or type(self.value) is not int):
                raise ContractValidationError("integer gate value must be an integer")
        elif self.value is not None:
            object.__setattr__(self, "value", _number(self.value, path="gate.value"))
        if self.value is None and self.applicable:
            raise ContractValidationError("applicable gate cannot have an undefined value")
        expected_passed = (
            True
            if not self.applicable and self.category == "stability"
            else self.value is not None and _op(self.value, self.threshold, self.operator)
        )
        if self.passed != expected_passed:
            raise ContractValidationError("lifecycle utility gate passed flag does not match value")

    def to_payload(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


class LifecycleUtilityDisposition(str, Enum):
    INVALID_EVIDENCE = "INVALID_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    LIFECYCLE_CONTEXT_SUPPORTED = "LIFECYCLE_CONTEXT_SUPPORTED"
    LIFECYCLE_CONTEXT_NOT_SUPPORTED = "LIFECYCLE_CONTEXT_NOT_SUPPORTED"


@dataclass(frozen=True)
class LifecycleUtilityDecision:
    contract_valid: bool
    disposition: LifecycleUtilityDisposition
    gates: tuple[GateResult, ...]
    reason: str

    def __post_init__(self) -> None:
        if type(self.contract_valid) is not bool:
            raise ContractValidationError("decision contract_valid must be boolean")
        if type(self.disposition) is not LifecycleUtilityDisposition:
            raise ContractValidationError("decision disposition is invalid")
        if type(self.gates) is not tuple or any(type(item) is not GateResult for item in self.gates) or tuple(item.name for item in self.gates) != _GATE_NAMES:
            raise ContractValidationError("decision gates do not match the exact approved schema")
        if type(self.reason) is not str or not self.reason:
            raise ContractValidationError("decision reason must be non-empty")
        readiness = tuple(item for item in self.gates if item.category == "readiness")
        quality = tuple(item for item in self.gates if item.category in {"quality", "stability"})
        if not self.contract_valid:
            expected = LifecycleUtilityDisposition.INVALID_EVIDENCE
        elif not all(item.passed for item in readiness):
            expected = LifecycleUtilityDisposition.INSUFFICIENT_EVIDENCE
        elif all(item.passed for item in quality):
            expected = LifecycleUtilityDisposition.LIFECYCLE_CONTEXT_SUPPORTED
        else:
            expected = LifecycleUtilityDisposition.LIFECYCLE_CONTEXT_NOT_SUPPORTED
        if self.disposition is not expected:
            raise ContractValidationError("decision disposition does not match gate precedence")

    def to_payload(self) -> dict[str, Any]:
        return {"contract_valid": self.contract_valid, "disposition": self.disposition.value, "gates": [item.to_payload() for item in self.gates], "reason": self.reason}


@dataclass(frozen=True)
class EventAccounting:
    source_case_count: int
    resolution_event_count: int
    unique_resolution_zone_count: int
    false_breakout_count: int
    break_confirmed_count: int
    completed_count: int
    right_censored_count: int

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _integer(getattr(self, name), path=f"event_accounting.{name}"))
        if self.resolution_event_count != self.false_breakout_count + self.break_confirmed_count:
            raise ContractValidationError("resolution event accounting does not reconcile")
        if self.resolution_event_count != self.unique_resolution_zone_count:
            raise ContractValidationError("resolution events must be deduplicated by unique zone")
        if self.completed_count + self.right_censored_count != self.resolution_event_count:
            raise ContractValidationError("resolution outcome accounting does not reconcile")

    def to_payload(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class LifecycleUtilityStudy:
    implementation_commit: str
    config_hash: str
    v19_bundle_id: str
    v19_study_id: str
    v10_bundle_id: str
    v10_audit_id: str
    source_bundle_id: str
    source_id: str
    bars_sha256: str
    null_cells: tuple[NullCell, ...]
    resolutions: tuple[ResolutionEvent, ...]
    outcomes: tuple[ResolutionOutcome, ...]
    fold_metrics: tuple[FoldMetrics, ...]
    aggregate: AggregateMetrics
    event_accounting: EventAccounting
    decision: LifecycleUtilityDecision
    study_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "implementation_commit", _commit(self.implementation_commit, path="study.implementation_commit"))
        for name in ("config_hash", "v19_bundle_id", "v19_study_id", "v10_bundle_id", "v10_audit_id", "source_bundle_id", "source_id", "bars_sha256"):
            object.__setattr__(self, name, _hash(getattr(self, name), path=f"study.{name}"))
        if (self.v19_bundle_id, self.v19_study_id, self.v10_bundle_id, self.v10_audit_id, self.source_bundle_id, self.source_id, self.bars_sha256) != (V19_BUNDLE_ID, V19_STUDY_ID, V10_BUNDLE_ID, V10_AUDIT_ID, FROZEN_SOURCE_BUNDLE_ID, FROZEN_SOURCE_ID, FROZEN_BARS_SHA256):
            raise ContractValidationError("study upstream/source identity is not approved")
        if type(self.null_cells) is not tuple or any(type(item) is not NullCell for item in self.null_cells):
            raise ContractValidationError("study null cells are invalid")
        expected_cells = {(fold, side) for fold in FROZEN_FOLD_NAMES for side in (ZoneSide.SUPPORT, ZoneSide.RESISTANCE)}
        if {(item.fold, item.effective_side) for item in self.null_cells} != expected_cells:
            raise ContractValidationError("study null cells do not cover the frozen fold/side grid")
        if tuple((item.fold, item.effective_side.value) for item in self.null_cells) != tuple(sorted(((item.fold, item.effective_side.value) for item in self.null_cells), key=lambda value: (FROZEN_FOLD_NAMES.index(value[0]), value[1]))):
            raise ContractValidationError("study null cells are not in canonical order")
        if type(self.resolutions) is not tuple or any(type(item) is not ResolutionEvent for item in self.resolutions):
            raise ContractValidationError("study resolutions are invalid")
        if type(self.outcomes) is not tuple or any(type(item) is not ResolutionOutcome for item in self.outcomes) or len(self.outcomes) != len(self.resolutions):
            raise ContractValidationError("study outcomes are invalid or do not reconcile")
        if len({item.zone_id for item in self.resolutions}) != len(self.resolutions) or len({item.resolution_id for item in self.resolutions}) != len(self.resolutions):
            raise ContractValidationError("study resolutions must be unique by zone and resolution")
        if self.resolutions != tuple(sorted(self.resolutions, key=lambda item: (item.event_at, item.zone_id, item.event_id))):
            raise ContractValidationError("study resolutions are not in canonical event order")
        if tuple(item.resolution_id for item in self.outcomes) != tuple(item.resolution_id for item in self.resolutions):
            raise ContractValidationError("study outcome/resolution ordering does not reconcile")
        if type(self.fold_metrics) is not tuple or tuple(item.fold for item in self.fold_metrics) != FROZEN_FOLD_NAMES:
            raise ContractValidationError("study fold metrics do not match the frozen fold order")
        if type(self.aggregate) is not AggregateMetrics or type(self.event_accounting) is not EventAccounting or type(self.decision) is not LifecycleUtilityDecision:
            raise ContractValidationError("study aggregate/accounting/decision types are invalid")
        if self.event_accounting.source_case_count != 36 or self.event_accounting.resolution_event_count != len(self.resolutions) or self.event_accounting.unique_resolution_zone_count != len({item.zone_id for item in self.resolutions}) or self.event_accounting.false_breakout_count != sum(item.event_class == "FALSE_BREAKOUT" for item in self.resolutions) or self.event_accounting.break_confirmed_count != sum(item.event_class == "BREAK_CONFIRMED" for item in self.resolutions) or self.event_accounting.completed_count != sum(item.completed for item in self.outcomes) or self.event_accounting.right_censored_count != sum(item.right_censored for item in self.outcomes):
            raise ContractValidationError("study event accounting does not reconcile with records")
        if self.aggregate.total_resolution_count != len(self.outcomes) or self.aggregate.completed_count != sum(item.completed for item in self.outcomes) or self.aggregate.right_censored_count != sum(item.right_censored for item in self.outcomes):
            raise ContractValidationError("study aggregate does not reconcile with outcomes")
        comparable_folds = {item.fold for item in self.fold_metrics if item.comparable}
        comparable_record_count = sum(item.compared and item.event_fold in comparable_folds for item in self.outcomes)
        if self.aggregate.compared_count != comparable_record_count or self.aggregate.comparable_fold_count != len(comparable_folds):
            raise ContractValidationError("study aggregate comparable metrics do not reconcile")
        for resolution, outcome in zip(self.resolutions, self.outcomes):
            if (
                outcome.zone_id != resolution.zone_id
                or outcome.case_id != resolution.case_id
                or outcome.event_id != resolution.event_id
                or outcome.event_class != resolution.event_class
                or outcome.event_at != resolution.event_at
                or outcome.event_bar_id != resolution.event_bar_id
                or outcome.event_fold != resolution.event_fold
                or outcome.original_side is not resolution.original_side
                or outcome.effective_side is not resolution.effective_side
                or outcome.anchor_close != resolution.anchor_close
                or outcome.reference_atr_14 != resolution.atr_at_event
            ):
                raise ContractValidationError("study outcome does not reconcile with its resolution event")
        object.__setattr__(self, "study_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "stage": "lifecycle_utility_development",
            "implementation_commit": self.implementation_commit,
            "config_hash": self.config_hash,
            "v19_bundle_id": self.v19_bundle_id,
            "v19_study_id": self.v19_study_id,
            "v10_bundle_id": self.v10_bundle_id,
            "v10_audit_id": self.v10_audit_id,
            "source_bundle_id": self.source_bundle_id,
            "source_id": self.source_id,
            "bars_sha256": self.bars_sha256,
            "null_cells": [item.to_payload() for item in self.null_cells],
            "resolutions": [item.to_payload() for item in self.resolutions],
            "outcomes": [item.to_payload() for item in self.outcomes],
            "fold_metrics": [item.to_payload() for item in self.fold_metrics],
            "aggregate": self.aggregate.to_payload(),
            "event_accounting": self.event_accounting.to_payload(),
            "decision": self.decision.to_payload(),
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "study_id": self.study_id}


def validate_study_payload(payload: Any, expected: LifecycleUtilityStudy) -> None:
    if type(payload) is not dict or payload != expected.to_payload():
        raise ContractValidationError("lifecycle utility study does not match semantic recomputation")


__all__ = [
    "AggregateMetrics", "EventAccounting", "EventClassMetrics", "FoldMetrics", "GateResult",
    "LifecycleUtilityDecision", "LifecycleUtilityDisposition", "LifecycleUtilityStudy",
    "NullCell", "ResolutionEvent", "ResolutionOutcome", "effective_side_for_event",
    "flipped_side", "validate_study_payload",
]
