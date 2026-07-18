"""Immutable V1.10 context-audit ledger contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import math
import re
from typing import Any

from libs.models.sr.domain import (
    ContractValidationError,
    SREventType,
    ZoneSide,
    ZoneStatus,
)
from libs.models.sr.domain.identity import deterministic_hash, require_utc, utc_isoformat
from libs.models.sr.evaluation import ZoneRenderKind


SCHEMA_VERSION = "1.0"
AUDIT_STAGE = "context_semantics_audit_development"
AUDIT_STATUS = "COMPLETE"
CASE_COUNT = 36
COMPARISON_COUNT = 31
FOLD_NAMES = (
    "2024_q3",
    "2024_q4",
    "2025_q1",
    "2025_q2",
    "2025_q3",
    "2025_q4",
)
SIDE_VALUES = (ZoneSide.SUPPORT, ZoneSide.RESISTANCE)
EVENT_VALUES = tuple(SREventType)
LIFECYCLE_EVENT_VALUES = (
    SREventType.TOUCHED,
    SREventType.BREACH_STARTED,
    SREventType.FALSE_BREAKOUT,
    SREventType.BREAK_CONFIRMED,
    SREventType.EXPIRED,
)

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


def _enum(value: Any, enum_type: type[Enum], *, path: str) -> Enum:
    if type(value) is not enum_type:
        raise ContractValidationError(f"{path} must be exactly {enum_type.__name__}")
    return value


def _tuple(value: Any, *, path: str) -> tuple[Any, ...]:
    if type(value) is not tuple:
        raise ContractValidationError(f"{path} must be exactly a tuple")
    return value


class CloseLocation(str, Enum):
    BELOW_BAND = "BELOW_BAND"
    INSIDE_BAND = "INSIDE_BAND"
    ABOVE_BAND = "ABOVE_BAND"


class HorizonLifecycleClass(str, Enum):
    BREAK_CONFIRMED = "BREAK_CONFIRMED"
    FALSE_BREAKOUT_NO_CONFIRMED_BREAK = "FALSE_BREAKOUT_NO_CONFIRMED_BREAK"
    EXPIRED_NO_BREAK_OR_FALSE_BREAKOUT = "EXPIRED_NO_BREAK_OR_FALSE_BREAKOUT"
    NO_TERMINAL_OR_FAKEOUT_EVENT = "NO_TERMINAL_OR_FAKEOUT_EVENT"


@dataclass(frozen=True)
class ZoneCaseView:
    zone_id: str
    side: ZoneSide
    source: str
    render_kind: ZoneRenderKind
    lower_bound: float
    center: float
    upper_bound: float
    atr_at_creation: float
    created_at: datetime
    available_at: datetime
    visible_from: datetime
    visible_until: datetime | None
    age_bars_at_touch: int
    touch_count_at_touch: int
    fakeout_count_at_touch: int
    pending_breach_count_at_touch: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "zone_id", _hash(self.zone_id, path="zone.zone_id"))
        object.__setattr__(self, "side", _enum(self.side, ZoneSide, path="zone.side"))
        object.__setattr__(self, "source", _string(self.source, path="zone.source"))
        object.__setattr__(self, "render_kind", _enum(self.render_kind, ZoneRenderKind, path="zone.render_kind"))
        for name in ("lower_bound", "center", "upper_bound"):
            object.__setattr__(self, name, _number(getattr(self, name), path=f"zone.{name}", minimum=0.0))
        if not self.lower_bound <= self.center <= self.upper_bound:
            raise ContractValidationError("zone bounds do not reconcile")
        if self.render_kind is ZoneRenderKind.LINE and not self.lower_bound == self.center == self.upper_bound:
            raise ContractValidationError("LINE zone geometry must have zero width")
        if self.render_kind is ZoneRenderKind.BAND and not self.lower_bound < self.center < self.upper_bound:
            raise ContractValidationError("BAND zone geometry must have positive width")
        object.__setattr__(self, "atr_at_creation", _number(self.atr_at_creation, path="zone.atr_at_creation", minimum=0.0))
        if self.atr_at_creation <= 0:
            raise ContractValidationError("zone.atr_at_creation must be positive")
        for name in ("created_at", "available_at", "visible_from"):
            object.__setattr__(self, name, _timestamp(getattr(self, name), path=f"zone.{name}"))
        if self.created_at > self.available_at or self.visible_from != self.available_at:
            raise ContractValidationError("zone creation/availability chronology is invalid")
        if self.visible_until is not None:
            object.__setattr__(self, "visible_until", _timestamp(self.visible_until, path="zone.visible_until"))
            if self.visible_until < self.visible_from:
                raise ContractValidationError("zone visible interval is inverted")
        for name in ("age_bars_at_touch", "touch_count_at_touch", "fakeout_count_at_touch", "pending_breach_count_at_touch"):
            object.__setattr__(self, name, _integer(getattr(self, name), path=f"zone.{name}"))

    def to_payload(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "side": self.side.value,
            "source": self.source,
            "render_kind": self.render_kind.value,
            "lower_bound": self.lower_bound,
            "center": self.center,
            "upper_bound": self.upper_bound,
            "atr_at_creation": self.atr_at_creation,
            "created_at": utc_isoformat(self.created_at),
            "available_at": utc_isoformat(self.available_at),
            "visible_from": utc_isoformat(self.visible_from),
            "visible_until": None if self.visible_until is None else utc_isoformat(self.visible_until),
            "age_bars_at_touch": self.age_bars_at_touch,
            "touch_count_at_touch": self.touch_count_at_touch,
            "fakeout_count_at_touch": self.fakeout_count_at_touch,
            "pending_breach_count_at_touch": self.pending_breach_count_at_touch,
        }


@dataclass(frozen=True)
class TouchBarView:
    bar_id: str
    open_time: datetime
    closed_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    reference_atr_14: float
    close_location: CloseLocation

    def __post_init__(self) -> None:
        object.__setattr__(self, "bar_id", _string(self.bar_id, path="touch_bar.bar_id"))
        object.__setattr__(self, "open_time", _timestamp(self.open_time, path="touch_bar.open_time"))
        object.__setattr__(self, "closed_at", _timestamp(self.closed_at, path="touch_bar.closed_at"))
        if self.closed_at <= self.open_time:
            raise ContractValidationError("touch bar chronology is invalid")
        for name in ("open", "high", "low", "close", "volume"):
            object.__setattr__(self, name, _number(getattr(self, name), path=f"touch_bar.{name}", minimum=0.0))
        if min(self.open, self.high, self.low, self.close) <= 0 or self.low > self.high or not self.low <= self.open <= self.high or not self.low <= self.close <= self.high:
            raise ContractValidationError("touch bar OHLC geometry is invalid")
        object.__setattr__(self, "reference_atr_14", _number(self.reference_atr_14, path="touch_bar.reference_atr_14", minimum=0.0))
        if self.reference_atr_14 <= 0:
            raise ContractValidationError("touch bar reference ATR must be positive")
        object.__setattr__(self, "close_location", _enum(self.close_location, CloseLocation, path="touch_bar.close_location"))

    def to_payload(self) -> dict[str, Any]:
        return {
            "bar_id": self.bar_id,
            "open_time": utc_isoformat(self.open_time),
            "closed_at": utc_isoformat(self.closed_at),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "reference_atr_14": self.reference_atr_14,
            "close_location": self.close_location.value,
        }


@dataclass(frozen=True)
class OutcomeView:
    completed: bool
    right_censored: bool
    invalidated: bool
    tenth_outcome_bar_closed_at: datetime | None
    anchor_close: float
    reference_atr_14: float
    favorable_reference_atr: float | None
    adverse_reference_atr: float | None
    quality_reference_atr: float | None

    def __post_init__(self) -> None:
        if type(self.completed) is not bool or type(self.right_censored) is not bool or type(self.invalidated) is not bool or self.completed == self.right_censored:
            raise ContractValidationError("outcome completion flags must be exactly completed or right-censored")
        if self.tenth_outcome_bar_closed_at is not None:
            object.__setattr__(self, "tenth_outcome_bar_closed_at", _timestamp(self.tenth_outcome_bar_closed_at, path="outcome.tenth_outcome_bar_closed_at"))
        object.__setattr__(self, "anchor_close", _number(self.anchor_close, path="outcome.anchor_close", minimum=0.0))
        object.__setattr__(self, "reference_atr_14", _number(self.reference_atr_14, path="outcome.reference_atr_14", minimum=0.0))
        if self.anchor_close <= 0 or self.reference_atr_14 <= 0:
            raise ContractValidationError("outcome anchor/reference values must be positive")
        values = (self.favorable_reference_atr, self.adverse_reference_atr, self.quality_reference_atr)
        if self.completed:
            if self.tenth_outcome_bar_closed_at is None or any(item is None for item in values):
                raise ContractValidationError("completed outcome requires horizon values")
            normalized = tuple(_number(item, path="outcome.metric", minimum=0.0 if index < 2 else None) for index, item in enumerate(values))
            if abs(normalized[2] - (normalized[0] - normalized[1])) > 1e-12:
                raise ContractValidationError("outcome quality formula mismatch")
            object.__setattr__(self, "favorable_reference_atr", normalized[0])
            object.__setattr__(self, "adverse_reference_atr", normalized[1])
            object.__setattr__(self, "quality_reference_atr", normalized[2])
        elif any(item is not None for item in values):
            raise ContractValidationError("right-censored outcome cannot contain horizon metrics")

    def to_payload(self) -> dict[str, Any]:
        return {
            "completed": self.completed,
            "right_censored": self.right_censored,
            "invalidated": self.invalidated,
            "tenth_outcome_bar_closed_at": None if self.tenth_outcome_bar_closed_at is None else utc_isoformat(self.tenth_outcome_bar_closed_at),
            "anchor_close": self.anchor_close,
            "reference_atr_14": self.reference_atr_14,
            "favorable_reference_atr": self.favorable_reference_atr,
            "adverse_reference_atr": self.adverse_reference_atr,
            "quality_reference_atr": self.quality_reference_atr,
        }


@dataclass(frozen=True)
class LifecycleEventView:
    event_id: str
    snapshot_id: str
    snapshot_as_of: datetime
    zone_id: str
    event_type: SREventType
    timestamp: datetime
    price: float
    bar_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _hash(self.event_id, path="event.event_id"))
        object.__setattr__(self, "snapshot_id", _hash(self.snapshot_id, path="event.snapshot_id"))
        object.__setattr__(self, "snapshot_as_of", _timestamp(self.snapshot_as_of, path="event.snapshot_as_of"))
        object.__setattr__(self, "zone_id", _hash(self.zone_id, path="event.zone_id"))
        object.__setattr__(self, "timestamp", _timestamp(self.timestamp, path="event.timestamp"))
        if self.timestamp > self.snapshot_as_of:
            raise ContractValidationError("event timestamp exceeds snapshot")
        object.__setattr__(self, "event_type", _enum(self.event_type, SREventType, path="event.event_type"))
        if self.event_type not in EVENT_VALUES:
            raise ContractValidationError("unsupported lifecycle event type")
        object.__setattr__(self, "price", _number(self.price, path="event.price", minimum=0.0))
        if self.price <= 0:
            raise ContractValidationError("event price must be positive")
        object.__setattr__(self, "bar_id", _string(self.bar_id, path="event.bar_id"))

    def to_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "snapshot_id": self.snapshot_id,
            "snapshot_as_of": utc_isoformat(self.snapshot_as_of),
            "zone_id": self.zone_id,
            "event_type": self.event_type.value,
            "timestamp": utc_isoformat(self.timestamp),
            "time": int(self.timestamp.timestamp()),
            "price": self.price,
            "bar_id": self.bar_id,
        }


@dataclass(frozen=True)
class ComparisonView:
    real_outcome_id: str
    fold: str
    side: ZoneSide
    real_quality: float
    null_median: float
    excess_quality: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "real_outcome_id", _hash(self.real_outcome_id, path="comparison.real_outcome_id"))
        object.__setattr__(self, "fold", _string(self.fold, path="comparison.fold"))
        object.__setattr__(self, "side", _enum(self.side, ZoneSide, path="comparison.side"))
        for name in ("real_quality", "null_median", "excess_quality"):
            object.__setattr__(self, name, _number(getattr(self, name), path=f"comparison.{name}"))
        if abs(self.excess_quality - (self.real_quality - self.null_median)) > 1e-12:
            raise ContractValidationError("comparison excess formula mismatch")

    def to_payload(self) -> dict[str, Any]:
        return {
            "real_outcome_id": self.real_outcome_id,
            "fold": self.fold,
            "side": self.side.value,
            "real_quality": self.real_quality,
            "null_median": self.null_median,
            "excess_quality": self.excess_quality,
        }


@dataclass(frozen=True)
class CaseLedger:
    record_id: str
    comparison_real_outcome_id: str | None
    zone_id: str
    side: ZoneSide
    fold: str
    touch_bar_id: str
    first_touch_at: datetime
    zone: ZoneCaseView
    touch_bar: TouchBarView
    entering_status: ZoneStatus
    after_touch_status: ZoneStatus
    pooled_outcome: OutcomeView
    fold_local_outcome: OutcomeView
    comparison: ComparisonView | None
    creation_event: LifecycleEventView
    lifecycle_events: tuple[LifecycleEventView, ...]
    horizon_lifecycle_class: HorizonLifecycleClass
    status_after_horizon: ZoneStatus
    case_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_id", _hash(self.record_id, path="case.record_id"))
        if self.comparison_real_outcome_id is not None:
            object.__setattr__(self, "comparison_real_outcome_id", _hash(self.comparison_real_outcome_id, path="case.comparison_real_outcome_id"))
        object.__setattr__(self, "zone_id", _hash(self.zone_id, path="case.zone_id"))
        object.__setattr__(self, "side", _enum(self.side, ZoneSide, path="case.side"))
        object.__setattr__(self, "fold", _string(self.fold, path="case.fold"))
        object.__setattr__(self, "touch_bar_id", _string(self.touch_bar_id, path="case.touch_bar_id"))
        object.__setattr__(self, "first_touch_at", _timestamp(self.first_touch_at, path="case.first_touch_at"))
        for name, expected_type in (("zone", ZoneCaseView), ("touch_bar", TouchBarView), ("pooled_outcome", OutcomeView), ("fold_local_outcome", OutcomeView), ("creation_event", LifecycleEventView)):
            if type(getattr(self, name)) is not expected_type:
                raise ContractValidationError(f"case.{name} has invalid type")
        if self.zone.zone_id != self.zone_id or self.zone.side is not self.side or self.touch_bar.bar_id != self.touch_bar_id or self.touch_bar.closed_at != self.first_touch_at:
            raise ContractValidationError("case identity does not reconcile with nested records")
        if self.creation_event.zone_id != self.zone_id:
            raise ContractValidationError("creation event zone identity does not reconcile")
        object.__setattr__(self, "entering_status", _enum(self.entering_status, ZoneStatus, path="case.entering_status"))
        object.__setattr__(self, "after_touch_status", _enum(self.after_touch_status, ZoneStatus, path="case.after_touch_status"))
        object.__setattr__(self, "status_after_horizon", _enum(self.status_after_horizon, ZoneStatus, path="case.status_after_horizon"))
        if self.creation_event.event_type is not SREventType.CREATED:
            raise ContractValidationError("case creation_event must be CREATED")
        if type(self.lifecycle_events) is not tuple or any(type(item) is not LifecycleEventView for item in self.lifecycle_events):
            raise ContractValidationError("case lifecycle_events must contain LifecycleEventView values")
        event_ids = [item.event_id for item in self.lifecycle_events]
        if len(set(event_ids)) != len(event_ids) or any(item.event_type is SREventType.CREATED for item in self.lifecycle_events) or any(item.zone_id != self.zone_id for item in self.lifecycle_events):
            raise ContractValidationError("case lifecycle events must exclude CREATED and be unique")
        object.__setattr__(self, "horizon_lifecycle_class", _enum(self.horizon_lifecycle_class, HorizonLifecycleClass, path="case.horizon_lifecycle_class"))
        horizon = self.pooled_outcome.tenth_outcome_bar_closed_at
        if horizon is None or any(item.timestamp < self.first_touch_at or item.timestamp > horizon for item in self.lifecycle_events):
            raise ContractValidationError("case lifecycle window is outside the approved horizon")
        if self.comparison is None:
            if self.comparison_real_outcome_id is not None:
                raise ContractValidationError("missing comparison cannot carry an ID")
        else:
            if type(self.comparison) is not ComparisonView or self.comparison.real_outcome_id != self.comparison_real_outcome_id or self.comparison.fold != self.fold or self.comparison.side is not self.side:
                raise ContractValidationError("case comparison identity does not reconcile")
        object.__setattr__(self, "case_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "record_id": self.record_id,
            "comparison_real_outcome_id": self.comparison_real_outcome_id,
            "zone_id": self.zone_id,
            "side": self.side.value,
            "fold": self.fold,
            "touch_bar_id": self.touch_bar_id,
            "first_touch_at": utc_isoformat(self.first_touch_at),
            "zone": self.zone.to_payload(),
            "touch_bar": self.touch_bar.to_payload(),
            "entering_status": self.entering_status.value,
            "after_touch_status": self.after_touch_status.value,
            "pooled_outcome": self.pooled_outcome.to_payload(),
            "fold_local_outcome": self.fold_local_outcome.to_payload(),
            "comparison": None if self.comparison is None else self.comparison.to_payload(),
            "creation_event": self.creation_event.to_payload(),
            "lifecycle_events": [item.to_payload() for item in self.lifecycle_events],
            "horizon_lifecycle_class": self.horizon_lifecycle_class.value,
            "status_after_horizon": self.status_after_horizon.value,
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "case_id": self.case_id}


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    values = sorted(values)
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2


@dataclass(frozen=True)
class AuditResult:
    implementation_commit: str
    config_hash: str
    v19_bundle_id: str
    v19_study_id: str
    v19_disposition: str
    source_bundle_id: str
    source_id: str
    trace_id: str
    audit_status: str
    cases: tuple[CaseLedger, ...]
    v19_parity: dict[str, Any]
    fold_side_decomposition: tuple[dict[str, Any], ...]
    lifecycle_decomposition: tuple[dict[str, Any], ...]
    touch_close_decomposition: tuple[dict[str, Any], ...]
    zone_age_summary: tuple[dict[str, Any], ...]
    controls: dict[str, Any]
    audit_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "implementation_commit", _commit(self.implementation_commit, path="audit.implementation_commit"))
        for name in ("config_hash", "v19_bundle_id", "v19_study_id", "source_bundle_id", "source_id", "trace_id"):
            object.__setattr__(self, name, _hash(getattr(self, name), path=f"audit.{name}"))
        if _string(self.v19_disposition, path="audit.v19_disposition") != "BASELINE_NOT_BETTER_THAN_NAIVE_NULL":
            raise ContractValidationError("V1.10 must preserve the V1.9 negative disposition")
        if _string(self.audit_status, path="audit.audit_status") != AUDIT_STATUS:
            raise ContractValidationError("audit_status must be COMPLETE")
        if type(self.cases) is not tuple or any(type(item) is not CaseLedger for item in self.cases) or len(self.cases) != CASE_COUNT:
            raise ContractValidationError("audit must contain exactly 36 typed cases")
        ordered = tuple(sorted(self.cases, key=lambda item: (item.first_touch_at, item.zone_id)))
        if ordered != self.cases:
            raise ContractValidationError("cases must be ordered by first_touch_at then zone_id")
        for name, values in (("case_id", [item.case_id for item in self.cases]), ("zone_id", [item.zone_id for item in self.cases]), ("record_id", [item.record_id for item in self.cases])):
            if len(set(values)) != len(values):
                raise ContractValidationError(f"audit {name}s must be unique")
        comparison_ids = [item.comparison_real_outcome_id for item in self.cases if item.comparison_real_outcome_id is not None]
        if len(comparison_ids) != COMPARISON_COUNT or len(set(comparison_ids)) != len(comparison_ids):
            raise ContractValidationError("audit comparison mapping must contain exactly 31 unique IDs")
        event_ids = [event.event_id for case in self.cases for event in (case.creation_event, *case.lifecycle_events)]
        if len(set(event_ids)) != len(event_ids):
            raise ContractValidationError("audit event identities must be unique")
        pooled_completed = sum(case.pooled_outcome.completed for case in self.cases)
        pooled_censored = sum(case.pooled_outcome.right_censored for case in self.cases)
        local_completed = sum(case.fold_local_outcome.completed for case in self.cases)
        local_censored = sum(case.fold_local_outcome.right_censored for case in self.cases)
        if (pooled_completed, pooled_censored, local_completed, local_censored) != (36, 0, 34, 2):
            raise ContractValidationError("audit outcome population counts do not reconcile")
        expected_keys = {"approved_pooled", "fold_local", "comparable_mapped", "aggregate", "fold_metrics", "fold_side_nulls", "comparisons", "control_accounting", "gates", "disposition"}
        if type(self.v19_parity) is not dict or set(self.v19_parity) != expected_keys:
            raise ContractValidationError("V1.9 parity table schema is incomplete")
        for name, values in (("fold_side_decomposition", self.fold_side_decomposition), ("lifecycle_decomposition", self.lifecycle_decomposition), ("touch_close_decomposition", self.touch_close_decomposition), ("zone_age_summary", self.zone_age_summary)):
            if type(values) is not tuple or any(type(item) is not dict for item in values):
                raise ContractValidationError(f"{name} must contain mapping rows")
        if type(self.controls) is not dict:
            raise ContractValidationError("audit controls must be a mapping")
        object.__setattr__(self, "audit_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "stage": AUDIT_STAGE,
            "implementation_commit": self.implementation_commit,
            "config_hash": self.config_hash,
            "v19_bundle_id": self.v19_bundle_id,
            "v19_study_id": self.v19_study_id,
            "v19_disposition": self.v19_disposition,
            "source_bundle_id": self.source_bundle_id,
            "source_id": self.source_id,
            "trace_id": self.trace_id,
            "audit_status": self.audit_status,
            "case_count": len(self.cases),
            "comparison_count": sum(item.comparison is not None for item in self.cases),
            "cases": [item.to_payload() for item in self.cases],
            "v19_parity": self.v19_parity,
            "fold_side_decomposition": list(self.fold_side_decomposition),
            "lifecycle_decomposition": list(self.lifecycle_decomposition),
            "touch_close_decomposition": list(self.touch_close_decomposition),
            "zone_age_summary": list(self.zone_age_summary),
            "controls": self.controls,
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "audit_id": self.audit_id}


def validate_audit_payload(payload: Any, expected: AuditResult) -> None:
    if type(payload) is not dict:
        raise ContractValidationError("audit.json must be a mapping")
    expected_payload = expected.to_payload()
    if set(payload) != set(expected_payload):
        raise ContractValidationError("audit.json schema does not match recomputed audit")
    if payload != expected_payload:
        raise ContractValidationError("audit.json does not match semantic recomputation")


__all__ = [
    "AUDIT_STAGE",
    "AUDIT_STATUS",
    "AuditResult",
    "CASE_COUNT",
    "CaseLedger",
    "CloseLocation",
    "ComparisonView",
    "HorizonLifecycleClass",
    "LifecycleEventView",
    "OutcomeView",
    "SCHEMA_VERSION",
    "TouchBarView",
    "ZoneCaseView",
    "validate_audit_payload",
]
