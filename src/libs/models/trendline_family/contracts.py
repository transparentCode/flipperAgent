"""Phase-A immutable contracts for the independent trendline-family model."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
import json
import math
import re
from types import MappingProxyType
from typing import Any, Callable, Mapping, TypeVar
from uuid import NAMESPACE_URL, uuid5


class ContractValidationError(ValueError):
    """Raised when a trendline-family contract is unsafe or invalid."""


class FamilyRole(str, Enum):
    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"
    UNCLASSIFIED = "UNCLASSIFIED"


class FamilyLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    ARCHIVED = "ARCHIVED"


class FamilyTransitionType(str, Enum):
    BIRTH = "BIRTH"
    CONTINUE = "CONTINUE"
    STRENGTHEN = "STRENGTHEN"
    WEAKEN = "WEAKEN"
    DORMANT = "DORMANT"
    REACTIVATE = "REACTIVATE"
    BREAK_CONFIRMED = "BREAK_CONFIRMED"
    ROLE_REVERSED = "ROLE_REVERSED"
    EXPIRE = "EXPIRE"


_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_T = TypeVar("_T")

# A deterministic tolerance for values produced by timestamp-space line
# projection and independently serialized audit fields.
_INTERACTION_FLOAT_TOLERANCE = 1e-9

_PHASE_G_DIAGNOSTIC_KEYS = frozenset(
    {
        "rail_group_count",
        "rail_grouping_rejection_reasons",
        "family_corridor_count",
        "singleton_family_count",
        "multi_rail_family_count",
        "total_rail_count",
        "representative_change_count",
    }
)


def _interaction_close(left: float, right: float) -> bool:
    """Compare persisted interaction audit values without changing their value."""

    return math.isclose(
        left,
        right,
        rel_tol=1e-12,
        abs_tol=_INTERACTION_FLOAT_TOLERANCE,
    )


def require_utc(timestamp: datetime, *, field_name: str = "timestamp") -> datetime:
    """Reject naive and non-UTC timestamps instead of silently changing geometry."""

    if not isinstance(timestamp, datetime):
        raise ContractValidationError(f"{field_name} must be a datetime")
    if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
        raise ContractValidationError(f"{field_name} must be timezone-aware UTC")
    return timestamp.astimezone(timezone.utc)


def utc_isoformat(timestamp: datetime) -> str:
    return require_utc(timestamp).isoformat().replace("+00:00", "Z")


def parse_utc_isoformat(value: Any, *, field_name: str = "timestamp") -> datetime:
    if not isinstance(value, str):
        raise ContractValidationError(f"{field_name} must be an ISO-8601 string")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractValidationError(f"{field_name} is not ISO-8601") from exc
    return require_utc(timestamp, field_name=field_name)


def _string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: Any, *, field_name: str) -> str | None:
    return None if value is None else _string(value, field_name=field_name)


def _integer(value: Any, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{field_name} must be an integer")
    if value < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    return value


def _optional_integer(value: Any, *, field_name: str, minimum: int = 0) -> int | None:
    return None if value is None else _integer(value, field_name=field_name, minimum=minimum)


def _number(value: Any, *, field_name: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ContractValidationError(f"{field_name} must be finite")
    if minimum is not None and number < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    if maximum is not None and number > maximum:
        raise ContractValidationError(f"{field_name} must be at most {maximum}")
    return number


def _optional_number(value: Any, *, field_name: str, minimum: float | None = None, maximum: float | None = None) -> float | None:
    return None if value is None else _number(value, field_name=field_name, minimum=minimum, maximum=maximum)


def _mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ContractValidationError(f"{field_name} must be a mapping with string keys")
    return value


def _required(value: Mapping[str, Any], key: str, *, owner: str) -> Any:
    if key not in value:
        raise ContractValidationError(f"{owner} missing required field: {key}")
    return value[key]


def _tuple_of_strings(value: Any, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise ContractValidationError(f"{field_name} must be a sequence")
    return tuple(_string(item, field_name=f"{field_name} item") for item in value)


def _freeze_value(value: Any, *, field_name: str) -> Any:
    """Recursively copy immutable metadata so published contracts cannot mutate."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return _number(value, field_name=field_name)
    if isinstance(value, datetime):
        return require_utc(value, field_name=field_name)
    if isinstance(value, Enum):
        return value
    if isinstance(value, Mapping):
        mapping = _mapping(value, field_name=field_name)
        return MappingProxyType({key: _freeze_value(item, field_name=f"{field_name}.{key}") for key, item in mapping.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_value(item, field_name=f"{field_name} item") for item in value)
    raise ContractValidationError(f"unsupported {field_name} value type: {type(value)!r}")


def _freeze_mapping(value: Mapping[str, Any] | None, *, field_name: str) -> Mapping[str, Any]:
    return _freeze_value(value or {}, field_name=field_name)


def _primitive(value: Any) -> Any:
    if isinstance(value, datetime):
        return utc_isoformat(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float):
        return _number(value, field_name="serialized float")
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Mapping):
        return {key: _primitive(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    if is_dataclass(value):
        return {item.name: _primitive(getattr(value, item.name)) for item in fields(value)}
    raise ContractValidationError(f"unsupported canonical value type: {type(value)!r}")


def canonical_json(value: Any) -> str:
    return json.dumps(_primitive(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def deterministic_id(kind: str, payload: Any) -> str:
    return str(uuid5(NAMESPACE_URL, f"trendline-family:{_string(kind, field_name='identity kind')}:{canonical_json(payload)}"))


def deterministic_hash(payload: Any) -> str:
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _role(value: Any) -> FamilyRole:
    try:
        return value if isinstance(value, FamilyRole) else FamilyRole(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid family role: {value!r}") from exc


def _lifecycle(value: Any) -> FamilyLifecycleState:
    try:
        return value if isinstance(value, FamilyLifecycleState) else FamilyLifecycleState(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid lifecycle state: {value!r}") from exc


def _transition_type(value: Any) -> FamilyTransitionType:
    try:
        return value if isinstance(value, FamilyTransitionType) else FamilyTransitionType(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid transition type: {value!r}") from exc


def _hash(value: Any, *, field_name: str) -> str:
    text = _string(value, field_name=field_name)
    if _HASH_PATTERN.fullmatch(text) is None:
        raise ContractValidationError(f"{field_name} must be a lowercase SHA-256 hex string")
    return text


def _decode(owner: str, value: Any, build: Callable[[Mapping[str, Any]], _T]) -> _T:
    mapping = _mapping(value, field_name=owner)
    try:
        return build(mapping)
    except ContractValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid {owner} payload") from exc


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


@dataclass(frozen=True)
class LineDiagnostics:
    raw_score: float
    normalized_quality: float
    touch_count: int
    effective_touch_count: int
    coverage: float
    r_squared: float | None = None
    inlier_ratio: float | None = None
    residual_scale_atr: float | None = None
    cut_fraction: float | None = None
    fitter_consensus: float | None = None
    anchor_stability: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_score", _number(self.raw_score, field_name="raw_score"))
        object.__setattr__(self, "normalized_quality", _number(self.normalized_quality, field_name="normalized_quality", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "touch_count", _integer(self.touch_count, field_name="touch_count"))
        object.__setattr__(self, "effective_touch_count", _integer(self.effective_touch_count, field_name="effective_touch_count"))
        if self.effective_touch_count > self.touch_count:
            raise ContractValidationError("effective_touch_count cannot exceed touch_count")
        object.__setattr__(self, "coverage", _number(self.coverage, field_name="coverage", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "r_squared", _optional_number(self.r_squared, field_name="r_squared", maximum=1.0))
        object.__setattr__(self, "inlier_ratio", _optional_number(self.inlier_ratio, field_name="inlier_ratio", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "residual_scale_atr", _optional_number(self.residual_scale_atr, field_name="residual_scale_atr", minimum=0.0))
        object.__setattr__(self, "cut_fraction", _optional_number(self.cut_fraction, field_name="cut_fraction", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "fitter_consensus", _optional_number(self.fitter_consensus, field_name="fitter_consensus", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "anchor_stability", _optional_number(self.anchor_stability, field_name="anchor_stability", minimum=0.0, maximum=1.0))

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LineDiagnostics":
        return _decode("LineDiagnostics", value, lambda item: cls(
            raw_score=_required(item, "raw_score", owner="LineDiagnostics"),
            normalized_quality=_required(item, "normalized_quality", owner="LineDiagnostics"),
            touch_count=_required(item, "touch_count", owner="LineDiagnostics"),
            effective_touch_count=_required(item, "effective_touch_count", owner="LineDiagnostics"),
            coverage=_required(item, "coverage", owner="LineDiagnostics"),
            r_squared=item.get("r_squared"), inlier_ratio=item.get("inlier_ratio"),
            residual_scale_atr=item.get("residual_scale_atr"), cut_fraction=item.get("cut_fraction"),
            fitter_consensus=item.get("fitter_consensus"), anchor_stability=item.get("anchor_stability"),
        ))


@dataclass(frozen=True)
class LineCandidate:
    candidate_id: str
    asset: str
    timeframe: str
    observed_at: datetime
    geometry: LineGeometry
    anchors: tuple[AnchorRef, ...]
    role: FamilyRole | str
    method: str
    provider: str
    diagnostics: LineDiagnostics
    source_line_index: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("candidate_id", "asset", "timeframe", "method", "provider"):
            object.__setattr__(self, name, _string(getattr(self, name), field_name=name))
        object.__setattr__(self, "observed_at", require_utc(self.observed_at, field_name="observed_at"))
        if not isinstance(self.geometry, LineGeometry) or not isinstance(self.diagnostics, LineDiagnostics):
            raise ContractValidationError("candidate geometry and diagnostics must use canonical contracts")
        anchors = tuple(self.anchors)
        if len(anchors) < 2 or any(not isinstance(anchor, AnchorRef) for anchor in anchors):
            raise ContractValidationError("a line candidate requires at least two anchors")
        if len({anchor.anchor_id for anchor in anchors}) != len(anchors):
            raise ContractValidationError("line candidate anchor IDs must be unique")
        if any(anchor.confirmation_time > self.observed_at for anchor in anchors):
            raise ContractValidationError("line candidate contains an anchor confirmed after observed_at")
        object.__setattr__(self, "anchors", anchors)
        object.__setattr__(self, "role", _role(self.role))
        object.__setattr__(self, "source_line_index", _optional_integer(self.source_line_index, field_name="source_line_index"))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, field_name="metadata"))

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LineCandidate":
        return _decode("LineCandidate", value, lambda item: cls(
            candidate_id=_required(item, "candidate_id", owner="LineCandidate"), asset=_required(item, "asset", owner="LineCandidate"),
            timeframe=_required(item, "timeframe", owner="LineCandidate"),
            observed_at=parse_utc_isoformat(_required(item, "observed_at", owner="LineCandidate"), field_name="observed_at"),
            geometry=LineGeometry.from_dict(_required(item, "geometry", owner="LineCandidate")),
            anchors=tuple(AnchorRef.from_dict(anchor) for anchor in _required(item, "anchors", owner="LineCandidate")),
            role=_required(item, "role", owner="LineCandidate"), method=_required(item, "method", owner="LineCandidate"),
            provider=_required(item, "provider", owner="LineCandidate"),
            diagnostics=LineDiagnostics.from_dict(_required(item, "diagnostics", owner="LineCandidate")),
            source_line_index=item.get("source_line_index"), metadata=item.get("metadata", {}),
        ))


@dataclass(frozen=True)
class InteractionZone:
    """A derived symmetric half-width around one exact representative line.

    ``width_atr`` is the selected price half-width divided by interaction ATR.
    """

    line_id: str
    timestamp: datetime
    center_price: float
    lower_price: float
    upper_price: float
    width_atr: float
    policy_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_id", _string(self.line_id, field_name="line_id"))
        object.__setattr__(self, "policy_name", _string(self.policy_name, field_name="policy_name"))
        object.__setattr__(self, "timestamp", require_utc(self.timestamp))
        for name in ("center_price", "lower_price", "upper_price"):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=name))
        object.__setattr__(self, "width_atr", _number(self.width_atr, field_name="width_atr", minimum=0.0))
        if self.lower_price > self.center_price or self.upper_price < self.center_price:
            raise ContractValidationError("interaction zone bounds are invalid")
        if not math.isclose(
            self.center_price - self.lower_price,
            self.upper_price - self.center_price,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ContractValidationError("interaction zone bounds must be symmetric around the exact center")

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InteractionZone":
        return _decode("InteractionZone", value, lambda item: cls(
            line_id=_required(item, "line_id", owner="InteractionZone"), timestamp=parse_utc_isoformat(_required(item, "timestamp", owner="InteractionZone")),
            center_price=_required(item, "center_price", owner="InteractionZone"), lower_price=_required(item, "lower_price", owner="InteractionZone"),
            upper_price=_required(item, "upper_price", owner="InteractionZone"), width_atr=_required(item, "width_atr", owner="InteractionZone"),
            policy_name=_required(item, "policy_name", owner="InteractionZone"),
        ))


class InteractionObservationState(str, Enum):
    FAR = "FAR"
    APPROACHING = "APPROACHING"
    IN_ZONE = "IN_ZONE"
    WICK_BREACH = "WICK_BREACH"
    BODY_BREACH = "BODY_BREACH"
    CLOSE_BEYOND = "CLOSE_BEYOND"


class InteractionEventState(str, Enum):
    """Persistent, confirmed-bar interaction lifecycle state."""

    FAR = "FAR"
    APPROACHING = "APPROACHING"
    IN_ZONE = "IN_ZONE"
    REJECTING = "REJECTING"
    PRESSURING = "PRESSURING"
    WICK_BREACHED = "WICK_BREACHED"
    BODY_BREACHED = "BODY_BREACHED"
    BREAK_PENDING = "BREAK_PENDING"
    BREAK_CONFIRMED = "BREAK_CONFIRMED"
    RETEST_PENDING = "RETEST_PENDING"
    RETEST_SUCCESS = "RETEST_SUCCESS"
    FAILED_BREAK = "FAILED_BREAK"
    ROLE_REVERSED = "ROLE_REVERSED"


class InteractionCompatibilityLabel(str, Enum):
    """Read-only legacy-friendly interpretation of persisted event evidence."""

    BREAKOUT = "breakout"
    BREAKDOWN = "breakdown"
    BOUNCE = "bounce"
    REJECTION = "rejection"


class CandleDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


def _interaction_state(value: Any) -> InteractionObservationState:
    try:
        return value if isinstance(value, InteractionObservationState) else InteractionObservationState(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid interaction observation state: {value!r}") from exc


def _event_state(value: Any) -> InteractionEventState:
    try:
        return value if isinstance(value, InteractionEventState) else InteractionEventState(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid interaction event state: {value!r}") from exc


def _candle_direction(value: Any) -> CandleDirection:
    try:
        return value if isinstance(value, CandleDirection) else CandleDirection(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid candle direction: {value!r}") from exc


@dataclass(frozen=True)
class FamilyInteractionObservation:
    """One confirmed-bar observation around an exact family representative line."""

    observation_id: str
    family_id: str
    role: FamilyRole | str
    timestamp: datetime
    state: InteractionObservationState | str
    exact_line_price: float
    zone: InteractionZone
    interaction_atr: float
    interaction_atr_method: str
    interaction_atr_sample_count: int
    distance_to_line_atr: float
    distance_to_zone_atr: float
    wick_penetration_atr: float
    body_penetration_atr: float
    close_penetration_atr: float
    candle_direction: CandleDirection | str
    close_location: float
    tick_size: float | None
    minimum_zone_ticks: int
    atr_half_width: float
    tick_half_width: float | None
    tick_floor_applied: bool
    # Added in Phase F so retest and failed-break logic can consume the
    # persisted confirmed-bar evidence without reclassifying a candle.
    close_price: float | None = None

    def __post_init__(self) -> None:
        for name in ("observation_id", "family_id", "interaction_atr_method"):
            object.__setattr__(self, name, _string(getattr(self, name), field_name=name))
        object.__setattr__(self, "role", _role(self.role))
        if self.role not in {FamilyRole.SUPPORT, FamilyRole.RESISTANCE}:
            raise ContractValidationError("interaction observation role must be SUPPORT or RESISTANCE")
        object.__setattr__(self, "timestamp", require_utc(self.timestamp, field_name="interaction timestamp"))
        object.__setattr__(self, "state", _interaction_state(self.state))
        object.__setattr__(self, "candle_direction", _candle_direction(self.candle_direction))
        if not isinstance(self.zone, InteractionZone):
            raise ContractValidationError("interaction observation zone must use InteractionZone")
        if self.zone.line_id != self.family_id or self.zone.timestamp != self.timestamp:
            raise ContractValidationError("interaction observation zone must identify the same family and timestamp")
        object.__setattr__(self, "exact_line_price", _number(self.exact_line_price, field_name="exact_line_price"))
        if not _interaction_close(self.exact_line_price, self.zone.center_price):
            raise ContractValidationError("interaction observation exact line price must equal zone center")
        object.__setattr__(self, "interaction_atr", _number(self.interaction_atr, field_name="interaction_atr", minimum=0.0))
        if self.interaction_atr <= 0.0:
            raise ContractValidationError("interaction_atr must be positive")
        object.__setattr__(
            self,
            "interaction_atr_sample_count",
            _integer(self.interaction_atr_sample_count, field_name="interaction_atr_sample_count", minimum=1),
        )
        for name in (
            "distance_to_line_atr",
            "distance_to_zone_atr",
            "wick_penetration_atr",
            "body_penetration_atr",
            "close_penetration_atr",
            "atr_half_width",
        ):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=name, minimum=0.0))
        absolute_half_width = self.zone.upper_price - self.zone.center_price
        if not _interaction_close(self.zone.center_price - self.zone.lower_price, absolute_half_width):
            raise ContractValidationError("interaction observation zone bounds must have equal half-widths")
        if not _interaction_close(self.zone.width_atr, absolute_half_width / self.interaction_atr):
            raise ContractValidationError("interaction observation width_atr must match zone half-width and interaction ATR")
        if self.wick_penetration_atr + 1e-12 < self.body_penetration_atr:
            raise ContractValidationError("wick penetration cannot be below body penetration")
        if self.body_penetration_atr + 1e-12 < self.close_penetration_atr:
            raise ContractValidationError("body penetration cannot be below close penetration")
        penetrations = (
            self.wick_penetration_atr,
            self.body_penetration_atr,
            self.close_penetration_atr,
        )
        if self.state in {
            InteractionObservationState.FAR,
            InteractionObservationState.APPROACHING,
            InteractionObservationState.IN_ZONE,
        } and any(value != 0.0 for value in penetrations):
            raise ContractValidationError("non-breach observations cannot report adverse penetration")
        if self.state is InteractionObservationState.WICK_BREACH and (
            self.wick_penetration_atr <= 0.0
            or self.body_penetration_atr != 0.0
            or self.close_penetration_atr != 0.0
        ):
            raise ContractValidationError("WICK_BREACH requires only positive wick penetration")
        if self.state is InteractionObservationState.BODY_BREACH and (
            self.body_penetration_atr <= 0.0 or self.close_penetration_atr != 0.0
        ):
            raise ContractValidationError("BODY_BREACH requires positive body penetration and zero close penetration")
        if self.state is InteractionObservationState.CLOSE_BEYOND and self.close_penetration_atr <= 0.0:
            raise ContractValidationError("CLOSE_BEYOND requires positive close penetration")
        object.__setattr__(self, "close_location", _number(self.close_location, field_name="close_location", minimum=0.0, maximum=1.0))
        object.__setattr__(
            self,
            "minimum_zone_ticks",
            _integer(self.minimum_zone_ticks, field_name="minimum_zone_ticks", minimum=1),
        )
        if not isinstance(self.tick_floor_applied, bool):
            raise ContractValidationError("tick_floor_applied must be boolean")
        if self.tick_size is None:
            if self.tick_half_width is not None or self.tick_floor_applied:
                raise ContractValidationError("tick floor cannot apply without tick_size")
            selected_half_width = self.atr_half_width
        else:
            object.__setattr__(self, "tick_size", _number(self.tick_size, field_name="tick_size", minimum=0.0))
            if self.tick_size <= 0.0:
                raise ContractValidationError("tick_size must be positive when supplied")
            object.__setattr__(
                self,
                "tick_half_width",
                _number(self.tick_half_width, field_name="tick_half_width", minimum=0.0),
            )
            if self.tick_half_width <= 0.0:
                raise ContractValidationError("tick_half_width must be positive when tick_size is supplied")
            expected_tick_half_width = self.tick_size * self.minimum_zone_ticks
            if not _interaction_close(self.tick_half_width, expected_tick_half_width):
                raise ContractValidationError("tick_half_width must equal tick_size times minimum_zone_ticks")
            expected_tick_floor_applied = self.tick_half_width >= self.atr_half_width
            if self.tick_floor_applied is not expected_tick_floor_applied:
                raise ContractValidationError("tick_floor_applied must reflect the selected tick floor")
            selected_half_width = max(self.atr_half_width, self.tick_half_width)
        if not _interaction_close(absolute_half_width, selected_half_width):
            raise ContractValidationError("interaction observation zone half-width must match the selected ATR/tick width")
        expected_distance_to_zone = max(self.distance_to_line_atr - self.zone.width_atr, 0.0)
        if not _interaction_close(self.distance_to_zone_atr, expected_distance_to_zone):
            raise ContractValidationError("distance_to_zone_atr must use the close-based line-distance relation")
        object.__setattr__(self, "close_price", _optional_number(self.close_price, field_name="close_price"))
        if self.close_price is not None:
            expected_distance_to_line = abs(self.close_price - self.exact_line_price) / self.interaction_atr
            if not _interaction_close(self.distance_to_line_atr, expected_distance_to_line):
                raise ContractValidationError(
                    "interaction observation close_price must match distance_to_line_atr"
                )
            if self.role is FamilyRole.SUPPORT and self.state is InteractionObservationState.CLOSE_BEYOND and self.close_price >= self.zone.lower_price:
                raise ContractValidationError("support CLOSE_BEYOND close must be below the interaction zone")
            if self.role is FamilyRole.RESISTANCE and self.state is InteractionObservationState.CLOSE_BEYOND and self.close_price <= self.zone.upper_price:
                raise ContractValidationError("resistance CLOSE_BEYOND close must be above the interaction zone")

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilyInteractionObservation":
        return _decode("FamilyInteractionObservation", value, lambda item: cls(
            observation_id=_required(item, "observation_id", owner="FamilyInteractionObservation"),
            family_id=_required(item, "family_id", owner="FamilyInteractionObservation"),
            role=_required(item, "role", owner="FamilyInteractionObservation"),
            timestamp=parse_utc_isoformat(_required(item, "timestamp", owner="FamilyInteractionObservation"), field_name="interaction timestamp"),
            state=_required(item, "state", owner="FamilyInteractionObservation"),
            exact_line_price=_required(item, "exact_line_price", owner="FamilyInteractionObservation"),
            zone=InteractionZone.from_dict(_required(item, "zone", owner="FamilyInteractionObservation")),
            interaction_atr=_required(item, "interaction_atr", owner="FamilyInteractionObservation"),
            interaction_atr_method=_required(item, "interaction_atr_method", owner="FamilyInteractionObservation"),
            interaction_atr_sample_count=_required(item, "interaction_atr_sample_count", owner="FamilyInteractionObservation"),
            distance_to_line_atr=_required(item, "distance_to_line_atr", owner="FamilyInteractionObservation"),
            distance_to_zone_atr=_required(item, "distance_to_zone_atr", owner="FamilyInteractionObservation"),
            wick_penetration_atr=_required(item, "wick_penetration_atr", owner="FamilyInteractionObservation"),
            body_penetration_atr=_required(item, "body_penetration_atr", owner="FamilyInteractionObservation"),
            close_penetration_atr=_required(item, "close_penetration_atr", owner="FamilyInteractionObservation"),
            candle_direction=_required(item, "candle_direction", owner="FamilyInteractionObservation"),
            close_location=_required(item, "close_location", owner="FamilyInteractionObservation"),
            tick_size=item.get("tick_size"),
            minimum_zone_ticks=_required(item, "minimum_zone_ticks", owner="FamilyInteractionObservation"),
            atr_half_width=_required(item, "atr_half_width", owner="FamilyInteractionObservation"),
            tick_half_width=item.get("tick_half_width"),
            tick_floor_applied=_required(item, "tick_floor_applied", owner="FamilyInteractionObservation"),
            close_price=item.get("close_price"),
        ))


@dataclass(frozen=True)
class LineUncertainty:
    """Estimation diagnostics, distinct from the derived interaction zone."""

    anchor_instability: float | None = None
    fitter_disagreement: float | None = None
    projection_horizon_bars: int = 0
    estimated_width_atr: float | None = None
    method: str = "not_calibrated"

    def __post_init__(self) -> None:
        object.__setattr__(self, "anchor_instability", _optional_number(self.anchor_instability, field_name="anchor_instability", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "fitter_disagreement", _optional_number(self.fitter_disagreement, field_name="fitter_disagreement", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "projection_horizon_bars", _integer(self.projection_horizon_bars, field_name="projection_horizon_bars"))
        object.__setattr__(self, "estimated_width_atr", _optional_number(self.estimated_width_atr, field_name="estimated_width_atr", minimum=0.0))
        object.__setattr__(self, "method", _string(self.method, field_name="uncertainty method"))

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LineUncertainty":
        return _decode("LineUncertainty", value, lambda item: cls(
            anchor_instability=item.get("anchor_instability"), fitter_disagreement=item.get("fitter_disagreement"),
            projection_horizon_bars=item.get("projection_horizon_bars", 0), estimated_width_atr=item.get("estimated_width_atr"),
            method=item.get("method", "not_calibrated"),
        ))


@dataclass(frozen=True)
class FamilyMember:
    member_id: str
    candidate_id: str
    geometry: LineGeometry
    role: FamilyRole | str
    diagnostics: LineDiagnostics
    anchors: tuple[AnchorRef, ...]
    first_seen_at: datetime
    last_seen_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "member_id", _string(self.member_id, field_name="member_id"))
        object.__setattr__(self, "candidate_id", _string(self.candidate_id, field_name="candidate_id"))
        if not isinstance(self.geometry, LineGeometry) or not isinstance(self.diagnostics, LineDiagnostics):
            raise ContractValidationError("family member geometry and diagnostics must use canonical contracts")
        anchors = tuple(self.anchors)
        if len(anchors) < 2 or any(not isinstance(anchor, AnchorRef) for anchor in anchors):
            raise ContractValidationError("a family member requires at least two canonical anchors")
        if len({anchor.anchor_id for anchor in anchors}) != len(anchors):
            raise ContractValidationError("family member anchor IDs must be unique")
        object.__setattr__(self, "anchors", anchors)
        object.__setattr__(self, "role", _role(self.role))
        object.__setattr__(self, "first_seen_at", require_utc(self.first_seen_at, field_name="first_seen_at"))
        object.__setattr__(self, "last_seen_at", require_utc(self.last_seen_at, field_name="last_seen_at"))
        if self.last_seen_at < self.first_seen_at:
            raise ContractValidationError("last_seen_at cannot precede first_seen_at")
        if any(anchor.confirmation_time > self.last_seen_at for anchor in anchors):
            raise ContractValidationError("family member anchor confirmation cannot exceed last_seen_at")

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilyMember":
        return _decode("FamilyMember", value, lambda item: cls(
            member_id=_required(item, "member_id", owner="FamilyMember"), candidate_id=_required(item, "candidate_id", owner="FamilyMember"),
            geometry=LineGeometry.from_dict(_required(item, "geometry", owner="FamilyMember")), role=_required(item, "role", owner="FamilyMember"),
            diagnostics=LineDiagnostics.from_dict(_required(item, "diagnostics", owner="FamilyMember")),
            anchors=tuple(AnchorRef.from_dict(anchor) for anchor in _required(item, "anchors", owner="FamilyMember")),
            first_seen_at=parse_utc_isoformat(_required(item, "first_seen_at", owner="FamilyMember"), field_name="first_seen_at"),
            last_seen_at=parse_utc_isoformat(_required(item, "last_seen_at", owner="FamilyMember"), field_name="last_seen_at"),
        ))


@dataclass(frozen=True)
class TrendlineFamilyState:
    """Immutable published family state; future trackers use private accumulators."""

    family_id: str
    asset: str
    timeframe: str
    created_at: datetime
    updated_at: datetime
    last_confirmed_at: datetime
    age_bars: int
    representative: LineGeometry
    representative_member_id: str
    members: tuple[FamilyMember, ...]
    current_role: FamilyRole | str
    lifecycle_state: FamilyLifecycleState | str
    confidence: float
    structural_importance: float
    current_relevance: float
    touch_count: int
    effective_touch_count: int
    breach_count: int
    bars_since_touch: int
    bars_since_match: int
    uncertainty: LineUncertainty
    parent_family_ids: tuple[str, ...] = ()
    child_family_ids: tuple[str, ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        for name in ("family_id", "asset", "timeframe", "representative_member_id"):
            object.__setattr__(self, name, _string(getattr(self, name), field_name=name))
        for name in ("created_at", "updated_at", "last_confirmed_at"):
            object.__setattr__(self, name, require_utc(getattr(self, name), field_name=name))
        if not self.created_at <= self.last_confirmed_at <= self.updated_at:
            raise ContractValidationError("family timestamps must satisfy created_at <= last_confirmed_at <= updated_at")
        object.__setattr__(self, "current_role", _role(self.current_role))
        members = tuple(self.members)
        if not members or any(not isinstance(member, FamilyMember) for member in members):
            raise ContractValidationError("a family requires at least one canonical member")
        if len({member.member_id for member in members}) != len(members):
            raise ContractValidationError("family member IDs must be unique")
        if len({member.candidate_id for member in members}) != len(members):
            raise ContractValidationError("family current candidate IDs must be unique")
        if tuple(sorted(members, key=lambda member: member.member_id)) != members:
            raise ContractValidationError("family members must have deterministic member ID ordering")
        if any(member.role is not self.current_role for member in members):
            raise ContractValidationError("family members must share the current family role")
        representative_member = next((member for member in members if member.member_id == self.representative_member_id), None)
        if representative_member is None:
            raise ContractValidationError("representative_member_id must identify an existing member")
        if not isinstance(self.representative, LineGeometry) or self.representative != representative_member.geometry:
            raise ContractValidationError("representative must equal the selected member's exact geometry")
        if any(member.first_seen_at > self.updated_at or member.last_seen_at > self.updated_at for member in members):
            raise ContractValidationError("family member visibility cannot exceed family update time")
        if any(anchor.confirmation_time > self.last_confirmed_at for member in members for anchor in member.anchors):
            raise ContractValidationError("family member anchor confirmation cannot exceed family confirmation time")
        object.__setattr__(self, "members", members)
        object.__setattr__(self, "lifecycle_state", _lifecycle(self.lifecycle_state))
        for name in ("age_bars", "touch_count", "effective_touch_count", "breach_count", "bars_since_touch", "bars_since_match"):
            object.__setattr__(self, name, _integer(getattr(self, name), field_name=name))
        if self.effective_touch_count > self.touch_count:
            raise ContractValidationError("effective_touch_count cannot exceed touch_count")
        object.__setattr__(self, "version", _integer(self.version, field_name="version", minimum=1))
        for name in ("confidence", "structural_importance", "current_relevance"):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=name, minimum=0.0, maximum=1.0))
        if not isinstance(self.uncertainty, LineUncertainty):
            raise ContractValidationError("uncertainty must use LineUncertainty")
        object.__setattr__(self, "parent_family_ids", _tuple_of_strings(self.parent_family_ids, field_name="parent_family_ids"))
        object.__setattr__(self, "child_family_ids", _tuple_of_strings(self.child_family_ids, field_name="child_family_ids"))

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrendlineFamilyState":
        return _decode("TrendlineFamilyState", value, lambda item: cls(
            family_id=_required(item, "family_id", owner="TrendlineFamilyState"), asset=_required(item, "asset", owner="TrendlineFamilyState"),
            timeframe=_required(item, "timeframe", owner="TrendlineFamilyState"),
            created_at=parse_utc_isoformat(_required(item, "created_at", owner="TrendlineFamilyState"), field_name="created_at"),
            updated_at=parse_utc_isoformat(_required(item, "updated_at", owner="TrendlineFamilyState"), field_name="updated_at"),
            last_confirmed_at=parse_utc_isoformat(_required(item, "last_confirmed_at", owner="TrendlineFamilyState"), field_name="last_confirmed_at"),
            age_bars=_required(item, "age_bars", owner="TrendlineFamilyState"),
            representative=LineGeometry.from_dict(_required(item, "representative", owner="TrendlineFamilyState")),
            representative_member_id=_required(item, "representative_member_id", owner="TrendlineFamilyState"),
            members=tuple(FamilyMember.from_dict(member) for member in _required(item, "members", owner="TrendlineFamilyState")),
            current_role=_required(item, "current_role", owner="TrendlineFamilyState"), lifecycle_state=_required(item, "lifecycle_state", owner="TrendlineFamilyState"),
            confidence=_required(item, "confidence", owner="TrendlineFamilyState"), structural_importance=_required(item, "structural_importance", owner="TrendlineFamilyState"),
            current_relevance=_required(item, "current_relevance", owner="TrendlineFamilyState"), touch_count=_required(item, "touch_count", owner="TrendlineFamilyState"),
            effective_touch_count=_required(item, "effective_touch_count", owner="TrendlineFamilyState"), breach_count=_required(item, "breach_count", owner="TrendlineFamilyState"),
            bars_since_touch=_required(item, "bars_since_touch", owner="TrendlineFamilyState"), bars_since_match=_required(item, "bars_since_match", owner="TrendlineFamilyState"),
            uncertainty=LineUncertainty.from_dict(_required(item, "uncertainty", owner="TrendlineFamilyState")),
            parent_family_ids=tuple(item.get("parent_family_ids", ())), child_family_ids=tuple(item.get("child_family_ids", ())), version=item.get("version", 1),
        ))


@dataclass(frozen=True)
class FamilyTransition:
    transition_id: str
    family_id: str
    timestamp: datetime
    transition_type: FamilyTransitionType | str
    previous_version: int | None
    new_version: int
    matched_candidate_ids: tuple[str, ...]
    association_score: float | None
    reason_codes: tuple[str, ...]
    metrics: Mapping[str, float]
    model_version: str
    config_version: str
    resolved_config_hash: str
    added_member_ids: tuple[str, ...] = ()
    continued_member_ids: tuple[str, ...] = ()
    removed_member_ids: tuple[str, ...] = ()
    previous_representative_member_id: str | None = None
    current_representative_member_id: str | None = None
    representative_changed: bool = False
    previous_rail_count: int = 0
    current_rail_count: int = 0
    source_group_id: str | None = None
    source_group_candidate_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "transition_id", _string(self.transition_id, field_name="transition_id"))
        object.__setattr__(self, "family_id", _string(self.family_id, field_name="family_id"))
        object.__setattr__(self, "timestamp", require_utc(self.timestamp))
        object.__setattr__(self, "transition_type", _transition_type(self.transition_type))
        object.__setattr__(self, "previous_version", _optional_integer(self.previous_version, field_name="previous_version", minimum=1))
        object.__setattr__(self, "new_version", _integer(self.new_version, field_name="new_version", minimum=1))
        if self.transition_type is FamilyTransitionType.BIRTH:
            if self.previous_version is not None or self.new_version != 1:
                raise ContractValidationError("BIRTH transition requires previous_version=None and new_version=1")
        elif self.previous_version is None or self.new_version != self.previous_version + 1:
            raise ContractValidationError("non-BIRTH transition must advance exactly one version")
        matched_candidate_ids = _tuple_of_strings(
            self.matched_candidate_ids,
            field_name="matched_candidate_ids",
        )
        if len(set(matched_candidate_ids)) != len(matched_candidate_ids):
            raise ContractValidationError("matched_candidate_ids must not contain duplicates")
        object.__setattr__(self, "matched_candidate_ids", matched_candidate_ids)
        object.__setattr__(self, "association_score", _optional_number(self.association_score, field_name="association_score", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "reason_codes", _tuple_of_strings(self.reason_codes, field_name="reason_codes"))
        metrics = _mapping(self.metrics, field_name="metrics")
        object.__setattr__(self, "metrics", MappingProxyType({key: _number(value, field_name=f"metrics.{key}") for key, value in metrics.items()}))
        object.__setattr__(self, "model_version", _string(self.model_version, field_name="model_version"))
        object.__setattr__(self, "config_version", _string(self.config_version, field_name="config_version"))
        object.__setattr__(self, "resolved_config_hash", _hash(self.resolved_config_hash, field_name="resolved_config_hash"))
        for name in ("added_member_ids", "continued_member_ids", "removed_member_ids"):
            values = _tuple_of_strings(getattr(self, name), field_name=name)
            if len(set(values)) != len(values):
                raise ContractValidationError(f"{name} must not contain duplicates")
            object.__setattr__(self, name, values)
        if set(self.added_member_ids) & set(self.continued_member_ids):
            raise ContractValidationError("added and continued member IDs must be disjoint")
        if set(self.removed_member_ids) & (set(self.added_member_ids) | set(self.continued_member_ids)):
            raise ContractValidationError("removed member IDs must be disjoint from current members")
        object.__setattr__(
            self,
            "previous_representative_member_id",
            _optional_string(
                self.previous_representative_member_id,
                field_name="previous_representative_member_id",
            ),
        )
        object.__setattr__(
            self,
            "current_representative_member_id",
            _optional_string(
                self.current_representative_member_id,
                field_name="current_representative_member_id",
            ),
        )
        if not isinstance(self.representative_changed, bool):
            raise ContractValidationError("representative_changed must be boolean")
        object.__setattr__(
            self,
            "previous_rail_count",
            _integer(self.previous_rail_count, field_name="previous_rail_count", minimum=0),
        )
        object.__setattr__(
            self,
            "current_rail_count",
            _integer(self.current_rail_count, field_name="current_rail_count", minimum=0),
        )
        object.__setattr__(
            self,
            "source_group_id",
            _optional_string(self.source_group_id, field_name="source_group_id"),
        )
        source_group_candidate_ids = _tuple_of_strings(
            self.source_group_candidate_ids,
            field_name="source_group_candidate_ids",
        )
        if len(set(source_group_candidate_ids)) != len(source_group_candidate_ids):
            raise ContractValidationError("source_group_candidate_ids must not contain duplicates")
        object.__setattr__(
            self,
            "source_group_candidate_ids",
            source_group_candidate_ids,
        )
        if self.previous_rail_count != len(self.continued_member_ids) + len(self.removed_member_ids):
            raise ContractValidationError("previous_rail_count must match continued and removed members")
        if self.current_rail_count != len(self.continued_member_ids) + len(self.added_member_ids):
            raise ContractValidationError("current_rail_count must match continued and added members")
        if self.representative_changed is not (
            self.previous_representative_member_id is not None
            and self.current_representative_member_id is not None
            and self.previous_representative_member_id
            != self.current_representative_member_id
        ):
            raise ContractValidationError("representative_changed must match representative IDs")

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilyTransition":
        return _decode("FamilyTransition", value, lambda item: cls(
            transition_id=_required(item, "transition_id", owner="FamilyTransition"), family_id=_required(item, "family_id", owner="FamilyTransition"),
            timestamp=parse_utc_isoformat(_required(item, "timestamp", owner="FamilyTransition")), transition_type=_required(item, "transition_type", owner="FamilyTransition"),
            previous_version=item.get("previous_version"), new_version=_required(item, "new_version", owner="FamilyTransition"),
            matched_candidate_ids=tuple(_required(item, "matched_candidate_ids", owner="FamilyTransition")), association_score=item.get("association_score"),
            reason_codes=tuple(_required(item, "reason_codes", owner="FamilyTransition")), metrics=_required(item, "metrics", owner="FamilyTransition"),
            model_version=_required(item, "model_version", owner="FamilyTransition"), config_version=_required(item, "config_version", owner="FamilyTransition"),
            resolved_config_hash=_required(item, "resolved_config_hash", owner="FamilyTransition"),
            added_member_ids=tuple(item.get("added_member_ids", ())),
            continued_member_ids=tuple(item.get("continued_member_ids", ())),
            removed_member_ids=tuple(item.get("removed_member_ids", ())),
            previous_representative_member_id=item.get("previous_representative_member_id"),
            current_representative_member_id=item.get("current_representative_member_id"),
            representative_changed=item.get("representative_changed", False),
            previous_rail_count=item.get("previous_rail_count", 0),
            current_rail_count=item.get("current_rail_count", 0),
            source_group_id=item.get("source_group_id"),
            source_group_candidate_ids=tuple(item.get("source_group_candidate_ids", ())),
        ))


@dataclass(frozen=True)
class FamilySourceGroupAudit:
    """Bounded canonical evidence for one candidate group used by an update."""

    source_group_id: str
    asset: str
    timeframe: str
    role: FamilyRole | str
    observed_at: datetime
    candidate_ids: tuple[str, ...]
    candidates: tuple[LineCandidate, ...]
    candidate_content_hashes: tuple[str, ...]
    model_version: str
    config_version: str
    resolved_config_hash: str

    def __post_init__(self) -> None:
        for name in (
            "source_group_id",
            "asset",
            "timeframe",
            "model_version",
            "config_version",
        ):
            object.__setattr__(self, name, _string(getattr(self, name), field_name=name))
        object.__setattr__(self, "role", _role(self.role))
        if self.role not in {FamilyRole.SUPPORT, FamilyRole.RESISTANCE}:
            raise ContractValidationError("source group role must be SUPPORT or RESISTANCE")
        object.__setattr__(
            self,
            "observed_at",
            require_utc(self.observed_at, field_name="source group observed_at"),
        )
        candidate_ids = _tuple_of_strings(
            self.candidate_ids,
            field_name="source group candidate_ids",
        )
        if not candidate_ids or tuple(sorted(candidate_ids)) != candidate_ids:
            raise ContractValidationError("source group candidate_ids must be non-empty and ordered")
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ContractValidationError("source group candidate_ids must be unique")
        object.__setattr__(self, "candidate_ids", candidate_ids)
        candidates = tuple(self.candidates)
        if len(candidates) != len(candidate_ids) or any(
            not isinstance(candidate, LineCandidate) for candidate in candidates
        ):
            raise ContractValidationError("source group requires canonical candidates")
        if tuple(candidate.candidate_id for candidate in candidates) != candidate_ids:
            raise ContractValidationError("source group candidates must match ordered candidate_ids")
        if any(
            candidate.asset != self.asset
            or candidate.timeframe != self.timeframe
            or candidate.role is not self.role
            or candidate.observed_at != self.observed_at
            or candidate.metadata.get("model_version") != self.model_version
            or candidate.metadata.get("config_version") != self.config_version
            or candidate.metadata.get("resolved_config_hash") != self.resolved_config_hash
            for candidate in candidates
        ):
            raise ContractValidationError("source group candidate identity must match audit identity")
        object.__setattr__(self, "candidates", candidates)
        candidate_content_hashes = tuple(
            _hash(value, field_name="source group candidate content hash")
            for value in self.candidate_content_hashes
        )
        if len(candidate_content_hashes) != len(candidate_ids):
            raise ContractValidationError("source group candidate hashes must match candidate_ids")
        expected_candidate_hashes = tuple(
            deterministic_hash(candidate.to_dict()) for candidate in candidates
        )
        if candidate_content_hashes != expected_candidate_hashes:
            raise ContractValidationError("source group candidate hashes must match canonical candidates")
        object.__setattr__(self, "candidate_content_hashes", candidate_content_hashes)
        object.__setattr__(
            self,
            "resolved_config_hash",
            _hash(self.resolved_config_hash, field_name="source group resolved_config_hash"),
        )
        expected_id = deterministic_id("family-source-group-audit", self._identity_payload())
        if self.source_group_id != expected_id:
            raise ContractValidationError("source_group_id must be content-addressed")

    def _identity_payload(self) -> Mapping[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "role": self.role.value,
            "observed_at": self.observed_at,
            "candidate_ids": self.candidate_ids,
            "candidate_content_hashes": self.candidate_content_hashes,
            "model_version": self.model_version,
            "config_version": self.config_version,
            "resolved_config_hash": self.resolved_config_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilySourceGroupAudit":
        return _decode("FamilySourceGroupAudit", value, lambda item: cls(
            source_group_id=_required(item, "source_group_id", owner="FamilySourceGroupAudit"),
            asset=_required(item, "asset", owner="FamilySourceGroupAudit"),
            timeframe=_required(item, "timeframe", owner="FamilySourceGroupAudit"),
            role=_required(item, "role", owner="FamilySourceGroupAudit"),
            observed_at=parse_utc_isoformat(
                _required(item, "observed_at", owner="FamilySourceGroupAudit"),
                field_name="source group observed_at",
            ),
            candidate_ids=tuple(_required(item, "candidate_ids", owner="FamilySourceGroupAudit")),
            candidates=tuple(
                LineCandidate.from_dict(candidate)
                for candidate in _required(item, "candidates", owner="FamilySourceGroupAudit")
            ),
            candidate_content_hashes=tuple(
                _required(item, "candidate_content_hashes", owner="FamilySourceGroupAudit")
            ),
            model_version=_required(item, "model_version", owner="FamilySourceGroupAudit"),
            config_version=_required(item, "config_version", owner="FamilySourceGroupAudit"),
            resolved_config_hash=_required(
                item,
                "resolved_config_hash",
                owner="FamilySourceGroupAudit",
            ),
        ))


@dataclass(frozen=True)
class FamilyRailProjection:
    """Timestamp-specific derived facts for one canonical exact member rail."""

    member_id: str
    order_index: int
    projected_price: float
    offset_from_representative_atr: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "member_id", _string(self.member_id, field_name="rail member_id"))
        object.__setattr__(
            self,
            "order_index",
            _integer(self.order_index, field_name="rail order_index", minimum=0),
        )
        object.__setattr__(
            self,
            "projected_price",
            _number(self.projected_price, field_name="rail projected_price"),
        )
        object.__setattr__(
            self,
            "offset_from_representative_atr",
            _number(
                self.offset_from_representative_atr,
                field_name="rail offset_from_representative_atr",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilyRailProjection":
        return _decode("FamilyRailProjection", value, lambda item: cls(
            member_id=_required(item, "member_id", owner="FamilyRailProjection"),
            order_index=_required(item, "order_index", owner="FamilyRailProjection"),
            projected_price=_required(item, "projected_price", owner="FamilyRailProjection"),
            offset_from_representative_atr=_required(
                item,
                "offset_from_representative_atr",
                owner="FamilyRailProjection",
            ),
        ))


@dataclass(frozen=True)
class FamilyCorridor:
    """Derived structural envelope across exact rails, never an interaction zone."""

    corridor_id: str
    family_id: str
    asset: str
    timeframe: str
    timestamp: datetime
    role: FamilyRole | str
    ordered_member_ids: tuple[str, ...]
    representative_member_id: str
    representative_slope_per_second: float
    lower_price: float
    upper_price: float
    center_price: float
    width_absolute: float
    width_atr: float
    rail_count: int
    max_adjacent_gap_atr: float | None
    median_adjacent_gap_atr: float | None
    spacing_stability: float | None
    rails: tuple[FamilyRailProjection, ...]
    center_policy: str
    model_version: str
    config_version: str
    resolved_config_hash: str

    def __post_init__(self) -> None:
        for name in (
            "corridor_id",
            "family_id",
            "asset",
            "timeframe",
            "representative_member_id",
            "center_policy",
            "model_version",
            "config_version",
        ):
            object.__setattr__(self, name, _string(getattr(self, name), field_name=name))
        object.__setattr__(self, "timestamp", require_utc(self.timestamp, field_name="corridor timestamp"))
        object.__setattr__(self, "role", _role(self.role))
        if self.role not in {FamilyRole.SUPPORT, FamilyRole.RESISTANCE}:
            raise ContractValidationError("corridor role must be SUPPORT or RESISTANCE")
        ordered_member_ids = _tuple_of_strings(
            self.ordered_member_ids,
            field_name="corridor ordered_member_ids",
        )
        if not ordered_member_ids or len(set(ordered_member_ids)) != len(ordered_member_ids):
            raise ContractValidationError("corridor ordered_member_ids must be unique and non-empty")
        object.__setattr__(self, "ordered_member_ids", ordered_member_ids)
        if self.representative_member_id not in ordered_member_ids:
            raise ContractValidationError("corridor representative_member_id must be ordered")
        for name in (
            "representative_slope_per_second",
            "lower_price",
            "upper_price",
            "center_price",
            "width_absolute",
            "width_atr",
        ):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=f"corridor {name}", minimum=0.0 if name in {"width_absolute", "width_atr"} else None))
        if self.lower_price > self.upper_price:
            raise ContractValidationError("corridor lower_price cannot exceed upper_price")
        if not _interaction_close(self.width_absolute, self.upper_price - self.lower_price):
            raise ContractValidationError("corridor width_absolute must match lower/upper prices")
        if not self.lower_price <= self.center_price <= self.upper_price:
            raise ContractValidationError("corridor center_price must be inside the corridor")
        if self.center_policy != "representative_exact_rail_v1":
            raise ContractValidationError("corridor center_policy must be representative_exact_rail_v1")
        object.__setattr__(self, "rail_count", _integer(self.rail_count, field_name="corridor rail_count", minimum=1))
        rails = tuple(self.rails)
        if len(rails) != self.rail_count or any(not isinstance(rail, FamilyRailProjection) for rail in rails):
            raise ContractValidationError("corridor rails must match rail_count")
        if tuple(rail.member_id for rail in rails) != self.ordered_member_ids:
            raise ContractValidationError("corridor rails must follow ordered_member_ids")
        if tuple(rail.order_index for rail in rails) != tuple(range(self.rail_count)):
            raise ContractValidationError("corridor rail order indexes must be contiguous")
        if tuple(
            sorted(rails, key=lambda rail: (rail.projected_price, rail.member_id))
        ) != rails:
            raise ContractValidationError("corridor rails must be ordered by projected price then member ID")
        object.__setattr__(self, "rails", rails)
        if not _interaction_close(self.lower_price, rails[0].projected_price):
            raise ContractValidationError("corridor lower_price must match its first exact rail")
        if not _interaction_close(self.upper_price, rails[-1].projected_price):
            raise ContractValidationError("corridor upper_price must match its last exact rail")
        representative_rail = next(
            rail for rail in rails if rail.member_id == self.representative_member_id
        )
        if not _interaction_close(self.center_price, representative_rail.projected_price):
            raise ContractValidationError("corridor center_price must match its representative exact rail")
        for name in (
            "max_adjacent_gap_atr",
            "median_adjacent_gap_atr",
            "spacing_stability",
        ):
            maximum = 1.0 if name == "spacing_stability" else None
            object.__setattr__(
                self,
                name,
                _optional_number(getattr(self, name), field_name=f"corridor {name}", minimum=0.0, maximum=maximum),
            )
        if self.rail_count == 1:
            if (
                self.lower_price != self.upper_price
                or self.center_price != self.lower_price
                or self.width_absolute != 0.0
                or self.width_atr != 0.0
                or self.max_adjacent_gap_atr is not None
                or self.median_adjacent_gap_atr is not None
                or self.spacing_stability is not None
            ):
                raise ContractValidationError("singleton corridor requires zero widths and undefined spacing diagnostics")
        elif (
            self.width_absolute <= 0.0
            or self.width_atr <= 0.0
            or self.max_adjacent_gap_atr is None
            or self.median_adjacent_gap_atr is None
            or self.spacing_stability is None
            or self.median_adjacent_gap_atr > self.max_adjacent_gap_atr
        ):
            raise ContractValidationError("multi-rail corridor requires positive width and spacing diagnostics")
        object.__setattr__(
            self,
            "resolved_config_hash",
            _hash(self.resolved_config_hash, field_name="corridor resolved_config_hash"),
        )
        expected_id = deterministic_id("family-corridor", self._identity_payload())
        if self.corridor_id != expected_id:
            raise ContractValidationError("corridor_id must be content-addressed from corridor content")

    def _identity_payload(self) -> Mapping[str, Any]:
        return {
            "family_id": self.family_id,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "role": self.role.value,
            "ordered_member_ids": self.ordered_member_ids,
            "representative_member_id": self.representative_member_id,
            "representative_slope_per_second": self.representative_slope_per_second,
            "lower_price": self.lower_price,
            "upper_price": self.upper_price,
            "center_price": self.center_price,
            "width_absolute": self.width_absolute,
            "width_atr": self.width_atr,
            "rail_count": self.rail_count,
            "max_adjacent_gap_atr": self.max_adjacent_gap_atr,
            "median_adjacent_gap_atr": self.median_adjacent_gap_atr,
            "spacing_stability": self.spacing_stability,
            "rails": tuple(rail.to_dict() for rail in self.rails),
            "center_policy": self.center_policy,
            "model_version": self.model_version,
            "config_version": self.config_version,
            "resolved_config_hash": self.resolved_config_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilyCorridor":
        return _decode("FamilyCorridor", value, lambda item: cls(
            corridor_id=_required(item, "corridor_id", owner="FamilyCorridor"),
            family_id=_required(item, "family_id", owner="FamilyCorridor"),
            asset=_required(item, "asset", owner="FamilyCorridor"),
            timeframe=_required(item, "timeframe", owner="FamilyCorridor"),
            timestamp=parse_utc_isoformat(_required(item, "timestamp", owner="FamilyCorridor"), field_name="corridor timestamp"),
            role=_required(item, "role", owner="FamilyCorridor"),
            ordered_member_ids=tuple(_required(item, "ordered_member_ids", owner="FamilyCorridor")),
            representative_member_id=_required(item, "representative_member_id", owner="FamilyCorridor"),
            representative_slope_per_second=_required(item, "representative_slope_per_second", owner="FamilyCorridor"),
            lower_price=_required(item, "lower_price", owner="FamilyCorridor"),
            upper_price=_required(item, "upper_price", owner="FamilyCorridor"),
            center_price=_required(item, "center_price", owner="FamilyCorridor"),
            width_absolute=_required(item, "width_absolute", owner="FamilyCorridor"),
            width_atr=_required(item, "width_atr", owner="FamilyCorridor"),
            rail_count=_required(item, "rail_count", owner="FamilyCorridor"),
            max_adjacent_gap_atr=item.get("max_adjacent_gap_atr"),
            median_adjacent_gap_atr=item.get("median_adjacent_gap_atr"),
            spacing_stability=item.get("spacing_stability"),
            rails=tuple(FamilyRailProjection.from_dict(rail) for rail in _required(item, "rails", owner="FamilyCorridor")),
            center_policy=_required(item, "center_policy", owner="FamilyCorridor"),
            model_version=_required(item, "model_version", owner="FamilyCorridor"),
            config_version=_required(item, "config_version", owner="FamilyCorridor"),
            resolved_config_hash=_required(item, "resolved_config_hash", owner="FamilyCorridor"),
        ))


@dataclass(frozen=True)
class FamilyInteractionEvent:
    """Immutable multi-bar lifecycle evidence for one published family."""

    event_id: str
    family_id: str
    asset: str
    timeframe: str
    state: InteractionEventState | str
    started_at: datetime
    updated_at: datetime
    starting_role: FamilyRole | str
    current_event_role: FamilyRole | str
    previous_state: InteractionEventState | str | None
    last_observation_id: str
    age_bars: int
    bars_in_state: int
    pressure_bars: int | None
    rejection_bars: int | None
    close_beyond_streak: int | None
    retest_age_bars: int | None
    retest_contact_seen: bool
    retest_confirmation_streak: int | None
    retest_window_expired: bool
    role_reversal_applied: bool
    max_wick_penetration_atr: float
    max_body_penetration_atr: float
    max_close_penetration_atr: float
    break_pending_at: datetime | None
    break_confirmed_at: datetime | None
    retest_started_at: datetime | None
    retest_succeeded_at: datetime | None
    failed_break_at: datetime | None
    pending_role_reversal: bool
    required_close_confirmation_bars: int
    required_retest_confirmation_bars: int
    model_version: str
    config_version: str
    resolved_config_hash: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("event_id", "family_id", "asset", "timeframe", "last_observation_id", "model_version", "config_version"):
            object.__setattr__(self, name, _string(getattr(self, name), field_name=name))
        object.__setattr__(self, "state", _event_state(self.state))
        object.__setattr__(self, "previous_state", None if self.previous_state is None else _event_state(self.previous_state))
        object.__setattr__(self, "started_at", require_utc(self.started_at, field_name="event started_at"))
        object.__setattr__(self, "updated_at", require_utc(self.updated_at, field_name="event updated_at"))
        if self.started_at > self.updated_at:
            raise ContractValidationError("event started_at cannot follow updated_at")
        for name in (
            "break_pending_at",
            "break_confirmed_at",
            "retest_started_at",
            "retest_succeeded_at",
            "failed_break_at",
        ):
            value = getattr(self, name)
            normalized = None if value is None else require_utc(value, field_name=name)
            if normalized is not None and (normalized < self.started_at or normalized > self.updated_at):
                raise ContractValidationError(f"{name} must be within the event lifetime")
            object.__setattr__(self, name, normalized)
        object.__setattr__(self, "starting_role", _role(self.starting_role))
        object.__setattr__(self, "current_event_role", _role(self.current_event_role))
        if self.starting_role not in {FamilyRole.SUPPORT, FamilyRole.RESISTANCE}:
            raise ContractValidationError("event starting_role must be SUPPORT or RESISTANCE")
        if self.current_event_role not in {FamilyRole.SUPPORT, FamilyRole.RESISTANCE}:
            raise ContractValidationError("event current_event_role must be SUPPORT or RESISTANCE")
        for name in ("age_bars", "bars_in_state"):
            object.__setattr__(self, name, _integer(getattr(self, name), field_name=name, minimum=0))
        if self.age_bars < 1 or self.bars_in_state < 1:
            raise ContractValidationError("event age_bars and bars_in_state must be positive")
        for name in ("pressure_bars", "rejection_bars", "close_beyond_streak"):
            object.__setattr__(self, name, _optional_integer(getattr(self, name), field_name=name, minimum=0))
        object.__setattr__(self, "retest_age_bars", _optional_integer(self.retest_age_bars, field_name="retest_age_bars", minimum=0))
        if not isinstance(self.retest_contact_seen, bool):
            raise ContractValidationError("retest_contact_seen must be boolean")
        object.__setattr__(
            self,
            "retest_confirmation_streak",
            _optional_integer(
                self.retest_confirmation_streak,
                field_name="retest_confirmation_streak",
                minimum=0,
            ),
        )
        if not isinstance(self.retest_window_expired, bool):
            raise ContractValidationError("retest_window_expired must be boolean")
        if not isinstance(self.role_reversal_applied, bool):
            raise ContractValidationError("role_reversal_applied must be boolean")
        for name in (
            "max_wick_penetration_atr",
            "max_body_penetration_atr",
            "max_close_penetration_atr",
        ):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=name, minimum=0.0))
        if self.max_wick_penetration_atr + 1e-12 < self.max_body_penetration_atr:
            raise ContractValidationError("event wick maximum cannot be below body maximum")
        if self.max_body_penetration_atr + 1e-12 < self.max_close_penetration_atr:
            raise ContractValidationError("event body maximum cannot be below close maximum")
        if not isinstance(self.pending_role_reversal, bool):
            raise ContractValidationError("event pending_role_reversal must be boolean")
        object.__setattr__(
            self,
            "required_close_confirmation_bars",
            _integer(
                self.required_close_confirmation_bars,
                field_name="required_close_confirmation_bars",
                minimum=2,
            ),
        )
        object.__setattr__(
            self,
            "required_retest_confirmation_bars",
            _integer(
                self.required_retest_confirmation_bars,
                field_name="required_retest_confirmation_bars",
                minimum=1,
            ),
        )
        if self.break_pending_at is not None and self.break_confirmed_at is not None and self.break_pending_at > self.break_confirmed_at:
            raise ContractValidationError("break_pending_at cannot follow break_confirmed_at")
        if self.break_confirmed_at is not None and self.retest_started_at is not None and self.break_confirmed_at > self.retest_started_at:
            raise ContractValidationError("break_confirmed_at cannot follow retest_started_at")
        if self.retest_started_at is not None and self.retest_succeeded_at is not None and self.retest_started_at > self.retest_succeeded_at:
            raise ContractValidationError("retest_started_at cannot follow retest_succeeded_at")
        if self.break_confirmed_at is not None and self.failed_break_at is not None and self.break_confirmed_at > self.failed_break_at:
            raise ContractValidationError("break_confirmed_at cannot follow failed_break_at")
        if self.state is InteractionEventState.BREAK_PENDING:
            if self.break_pending_at is None or self.close_beyond_streak is None or self.close_beyond_streak < 1:
                raise ContractValidationError("BREAK_PENDING requires a pending timestamp and close streak")
        if self.state in {
            InteractionEventState.BREAK_CONFIRMED,
            InteractionEventState.RETEST_PENDING,
            InteractionEventState.RETEST_SUCCESS,
            InteractionEventState.FAILED_BREAK,
            InteractionEventState.ROLE_REVERSED,
        }:
            if self.break_confirmed_at is None:
                raise ContractValidationError("post-break event states require break_confirmed_at")
        if self.state is InteractionEventState.BREAK_CONFIRMED and (
            self.close_beyond_streak is None
            or self.close_beyond_streak < self.required_close_confirmation_bars
        ):
            raise ContractValidationError("BREAK_CONFIRMED requires the configured consecutive close evidence")
        if self.state is InteractionEventState.BREAK_CONFIRMED and (
            self.previous_state is not InteractionEventState.BREAK_PENDING
            or self.break_pending_at is None
        ):
            raise ContractValidationError("BREAK_CONFIRMED requires a BREAK_PENDING predecessor")
        retest_states = {
            InteractionEventState.RETEST_PENDING,
            InteractionEventState.RETEST_SUCCESS,
            InteractionEventState.ROLE_REVERSED,
        }
        if self.state in retest_states and self.retest_started_at is None:
            raise ContractValidationError("retest event states require retest_started_at")
        if self.state is InteractionEventState.RETEST_PENDING and (
            self.previous_state
            not in {InteractionEventState.BREAK_CONFIRMED, InteractionEventState.RETEST_PENDING}
            or self.retest_age_bars is None
            or self.retest_confirmation_streak is None
        ):
            raise ContractValidationError("RETEST_PENDING requires a valid post-break predecessor and typed retest state")
        if self.state in {InteractionEventState.RETEST_SUCCESS, InteractionEventState.ROLE_REVERSED} and self.retest_succeeded_at is None:
            raise ContractValidationError("successful retest states require retest_succeeded_at")
        if self.state is InteractionEventState.RETEST_SUCCESS and (
            self.previous_state is not InteractionEventState.RETEST_PENDING
            or not self.retest_contact_seen
            or self.retest_confirmation_streak is None
            or self.retest_confirmation_streak < self.required_retest_confirmation_bars
        ):
            raise ContractValidationError("RETEST_SUCCESS requires typed confirmed retest evidence")
        if self.state is InteractionEventState.FAILED_BREAK and self.failed_break_at is None:
            raise ContractValidationError("FAILED_BREAK requires failed_break_at")
        if self.state is InteractionEventState.FAILED_BREAK and self.previous_state not in {
            InteractionEventState.BREAK_CONFIRMED,
            InteractionEventState.RETEST_PENDING,
        }:
            raise ContractValidationError("FAILED_BREAK requires a post-break predecessor")
        if self.pending_role_reversal is not (self.state is InteractionEventState.RETEST_SUCCESS):
            raise ContractValidationError("pending role reversal is valid only for RETEST_SUCCESS")
        if self.state is InteractionEventState.ROLE_REVERSED:
            if (
                self.current_event_role is self.starting_role
                or self.previous_state is not InteractionEventState.RETEST_SUCCESS
                or not self.role_reversal_applied
            ):
                raise ContractValidationError("ROLE_REVERSED requires a successful pending retest reversal")
        elif self.current_event_role is not self.starting_role:
            raise ContractValidationError("only ROLE_REVERSED may change the current event role")
        elif self.role_reversal_applied:
            raise ContractValidationError("role_reversal_applied is valid only for ROLE_REVERSED")
        if self.state not in retest_states and (
            self.retest_contact_seen
            or self.retest_confirmation_streak is not None
        ):
            raise ContractValidationError("non-retest event states cannot retain typed retest progress")
        if self.retest_window_expired and (
            self.state is not InteractionEventState.FAR
            or self.previous_state is not InteractionEventState.RETEST_PENDING
        ):
            raise ContractValidationError("retest window expiry must resolve directly from RETEST_PENDING to FAR")
        object.__setattr__(self, "resolved_config_hash", _hash(self.resolved_config_hash, field_name="resolved_config_hash"))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, field_name="event metadata"))

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilyInteractionEvent":
        return _decode("FamilyInteractionEvent", value, lambda item: cls(
            event_id=_required(item, "event_id", owner="FamilyInteractionEvent"),
            family_id=_required(item, "family_id", owner="FamilyInteractionEvent"),
            asset=_required(item, "asset", owner="FamilyInteractionEvent"),
            timeframe=_required(item, "timeframe", owner="FamilyInteractionEvent"),
            state=_required(item, "state", owner="FamilyInteractionEvent"),
            started_at=parse_utc_isoformat(_required(item, "started_at", owner="FamilyInteractionEvent"), field_name="event started_at"),
            updated_at=parse_utc_isoformat(_required(item, "updated_at", owner="FamilyInteractionEvent"), field_name="event updated_at"),
            starting_role=_required(item, "starting_role", owner="FamilyInteractionEvent"),
            current_event_role=_required(item, "current_event_role", owner="FamilyInteractionEvent"),
            previous_state=item.get("previous_state"),
            last_observation_id=_required(item, "last_observation_id", owner="FamilyInteractionEvent"),
            age_bars=_required(item, "age_bars", owner="FamilyInteractionEvent"),
            bars_in_state=_required(item, "bars_in_state", owner="FamilyInteractionEvent"),
            pressure_bars=_required(item, "pressure_bars", owner="FamilyInteractionEvent"),
            rejection_bars=_required(item, "rejection_bars", owner="FamilyInteractionEvent"),
            close_beyond_streak=_required(item, "close_beyond_streak", owner="FamilyInteractionEvent"),
            retest_age_bars=item.get("retest_age_bars"),
            retest_contact_seen=_required(item, "retest_contact_seen", owner="FamilyInteractionEvent"),
            retest_confirmation_streak=item.get("retest_confirmation_streak"),
            retest_window_expired=_required(item, "retest_window_expired", owner="FamilyInteractionEvent"),
            role_reversal_applied=_required(item, "role_reversal_applied", owner="FamilyInteractionEvent"),
            max_wick_penetration_atr=_required(item, "max_wick_penetration_atr", owner="FamilyInteractionEvent"),
            max_body_penetration_atr=_required(item, "max_body_penetration_atr", owner="FamilyInteractionEvent"),
            max_close_penetration_atr=_required(item, "max_close_penetration_atr", owner="FamilyInteractionEvent"),
            break_pending_at=None if item.get("break_pending_at") is None else parse_utc_isoformat(item["break_pending_at"], field_name="break_pending_at"),
            break_confirmed_at=None if item.get("break_confirmed_at") is None else parse_utc_isoformat(item["break_confirmed_at"], field_name="break_confirmed_at"),
            retest_started_at=None if item.get("retest_started_at") is None else parse_utc_isoformat(item["retest_started_at"], field_name="retest_started_at"),
            retest_succeeded_at=None if item.get("retest_succeeded_at") is None else parse_utc_isoformat(item["retest_succeeded_at"], field_name="retest_succeeded_at"),
            failed_break_at=None if item.get("failed_break_at") is None else parse_utc_isoformat(item["failed_break_at"], field_name="failed_break_at"),
            pending_role_reversal=_required(item, "pending_role_reversal", owner="FamilyInteractionEvent"),
            required_close_confirmation_bars=_required(item, "required_close_confirmation_bars", owner="FamilyInteractionEvent"),
            required_retest_confirmation_bars=_required(item, "required_retest_confirmation_bars", owner="FamilyInteractionEvent"),
            model_version=_required(item, "model_version", owner="FamilyInteractionEvent"),
            config_version=_required(item, "config_version", owner="FamilyInteractionEvent"),
            resolved_config_hash=_required(item, "resolved_config_hash", owner="FamilyInteractionEvent"),
            metadata=item.get("metadata", {}),
        ))


@dataclass(frozen=True)
class FamilyInteractionEventTransition:
    """Content-addressed audit record for one event-state transition."""

    transition_id: str
    event_id: str
    family_id: str
    from_state: InteractionEventState | str
    to_state: InteractionEventState | str
    timestamp: datetime
    trigger_observation_id: str
    reason_code: str
    bars_in_previous_state: int
    metrics: Mapping[str, float]
    model_version: str
    config_version: str
    resolved_config_hash: str

    def __post_init__(self) -> None:
        for name in ("transition_id", "event_id", "family_id", "trigger_observation_id", "reason_code", "model_version", "config_version"):
            object.__setattr__(self, name, _string(getattr(self, name), field_name=name))
        object.__setattr__(self, "from_state", _event_state(self.from_state))
        object.__setattr__(self, "to_state", _event_state(self.to_state))
        if self.from_state is self.to_state:
            raise ContractValidationError("event transition requires distinct states")
        object.__setattr__(self, "timestamp", require_utc(self.timestamp, field_name="event transition timestamp"))
        object.__setattr__(self, "bars_in_previous_state", _integer(self.bars_in_previous_state, field_name="bars_in_previous_state", minimum=1))
        metrics = _mapping(self.metrics, field_name="event transition metrics")
        object.__setattr__(self, "metrics", MappingProxyType({key: _number(value, field_name=f"event transition metrics.{key}") for key, value in metrics.items()}))
        object.__setattr__(self, "resolved_config_hash", _hash(self.resolved_config_hash, field_name="resolved_config_hash"))

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilyInteractionEventTransition":
        return _decode("FamilyInteractionEventTransition", value, lambda item: cls(
            transition_id=_required(item, "transition_id", owner="FamilyInteractionEventTransition"),
            event_id=_required(item, "event_id", owner="FamilyInteractionEventTransition"),
            family_id=_required(item, "family_id", owner="FamilyInteractionEventTransition"),
            from_state=_required(item, "from_state", owner="FamilyInteractionEventTransition"),
            to_state=_required(item, "to_state", owner="FamilyInteractionEventTransition"),
            timestamp=parse_utc_isoformat(_required(item, "timestamp", owner="FamilyInteractionEventTransition"), field_name="event transition timestamp"),
            trigger_observation_id=_required(item, "trigger_observation_id", owner="FamilyInteractionEventTransition"),
            reason_code=_required(item, "reason_code", owner="FamilyInteractionEventTransition"),
            bars_in_previous_state=_required(item, "bars_in_previous_state", owner="FamilyInteractionEventTransition"),
            metrics=_required(item, "metrics", owner="FamilyInteractionEventTransition"),
            model_version=_required(item, "model_version", owner="FamilyInteractionEventTransition"),
            config_version=_required(item, "config_version", owner="FamilyInteractionEventTransition"),
            resolved_config_hash=_required(item, "resolved_config_hash", owner="FamilyInteractionEventTransition"),
        ))


@dataclass(frozen=True)
class TrendlineFamilySnapshot:
    snapshot_id: str
    asset: str
    timeframe: str
    timestamp: datetime
    previous_snapshot_id: str | None
    model_version: str
    config_version: str
    resolved_config_hash: str
    active_families: tuple[TrendlineFamilyState, ...]
    dormant_families: tuple[TrendlineFamilyState, ...]
    transitions: tuple[FamilyTransition, ...]
    source_group_audits: tuple[FamilySourceGroupAudit, ...] = ()
    corridors: tuple[FamilyCorridor, ...] = ()
    observations: tuple[FamilyInteractionObservation, ...] = ()
    interaction_events: tuple[FamilyInteractionEvent, ...] = ()
    interaction_event_transitions: tuple[FamilyInteractionEventTransition, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "asset", "timeframe", "model_version", "config_version"):
            object.__setattr__(self, name, _string(getattr(self, name), field_name=name))
        object.__setattr__(self, "previous_snapshot_id", _optional_string(self.previous_snapshot_id, field_name="previous_snapshot_id"))
        object.__setattr__(self, "resolved_config_hash", _hash(self.resolved_config_hash, field_name="resolved_config_hash"))
        object.__setattr__(self, "timestamp", require_utc(self.timestamp))
        active_families, dormant_families, transitions = tuple(self.active_families), tuple(self.dormant_families), tuple(self.transitions)
        source_group_audits = tuple(self.source_group_audits)
        corridors = tuple(self.corridors)
        observations = tuple(self.observations)
        interaction_events = tuple(self.interaction_events)
        interaction_event_transitions = tuple(self.interaction_event_transitions)
        if any(not isinstance(family, TrendlineFamilyState) for family in active_families + dormant_families):
            raise ContractValidationError("snapshot families must use TrendlineFamilyState")
        if any(family.lifecycle_state is not FamilyLifecycleState.ACTIVE for family in active_families):
            raise ContractValidationError("active snapshot bucket may contain only ACTIVE families")
        if any(family.lifecycle_state is not FamilyLifecycleState.DORMANT for family in dormant_families):
            raise ContractValidationError("dormant snapshot bucket may contain only DORMANT families")
        if any(family.updated_at > self.timestamp or family.last_confirmed_at > self.timestamp for family in active_families + dormant_families):
            raise ContractValidationError("family timestamps cannot exceed snapshot timestamp")
        family_ids = [family.family_id for family in active_families + dormant_families]
        if len(family_ids) != len(set(family_ids)):
            raise ContractValidationError("a snapshot cannot contain duplicate family IDs")
        if any(family.asset != self.asset or family.timeframe != self.timeframe for family in active_families + dormant_families):
            raise ContractValidationError("snapshot family asset/timeframe mismatch")
        if any(not isinstance(transition, FamilyTransition) for transition in transitions):
            raise ContractValidationError("snapshot transitions must use FamilyTransition")
        if len({transition.transition_id for transition in transitions}) != len(transitions):
            raise ContractValidationError("snapshot transition IDs must be unique")
        if any(transition.timestamp > self.timestamp for transition in transitions):
            raise ContractValidationError("transition timestamp cannot exceed snapshot timestamp")
        if any(transition.model_version != self.model_version or transition.config_version != self.config_version or transition.resolved_config_hash != self.resolved_config_hash for transition in transitions):
            raise ContractValidationError("transition metadata must match the containing snapshot")
        present_families = {family.family_id: family for family in active_families + dormant_families}
        if any(not isinstance(audit, FamilySourceGroupAudit) for audit in source_group_audits):
            raise ContractValidationError("snapshot source_group_audits must use FamilySourceGroupAudit")
        if len({audit.source_group_id for audit in source_group_audits}) != len(source_group_audits):
            raise ContractValidationError("snapshot source group audit IDs must be unique")
        if source_group_audits and tuple(
            sorted(source_group_audits, key=lambda item: item.source_group_id)
        ) != source_group_audits:
            raise ContractValidationError("snapshot source group audits must have deterministic ordering")
        for transition in transitions:
            family = present_families.get(transition.family_id)
            if transition.transition_type is FamilyTransitionType.EXPIRE:
                if (
                    transition.current_rail_count != 0
                    or transition.current_representative_member_id is not None
                    or transition.added_member_ids
                    or transition.continued_member_ids
                ):
                    raise ContractValidationError("EXPIRE transition cannot retain current rail evidence")
                continue
            if family is None:
                raise ContractValidationError("non-EXPIRE transition must reference a published family")
            if transition.new_version != family.version:
                raise ContractValidationError("transition new_version must match its published family version")
        if any(not isinstance(corridor, FamilyCorridor) for corridor in corridors):
            raise ContractValidationError("snapshot corridors must use FamilyCorridor")
        if len({corridor.corridor_id for corridor in corridors}) != len(corridors):
            raise ContractValidationError("snapshot corridor IDs must be unique")
        if len({corridor.family_id for corridor in corridors}) != len(corridors):
            raise ContractValidationError("snapshot must contain one corridor per family")
        if corridors and tuple(sorted(corridors, key=lambda item: (item.family_id, item.corridor_id))) != corridors:
            raise ContractValidationError("snapshot corridors must have deterministic family ordering")
        phase_g_marker = _mapping(self.diagnostics, field_name="diagnostics").get("rail_grouping_enabled") is True
        if phase_g_marker and set(corridor.family_id for corridor in corridors) != set(present_families):
            raise ContractValidationError("Phase-G snapshot corridors must cover every published family")
        for corridor in corridors:
            family = present_families.get(corridor.family_id)
            if family is None:
                raise ContractValidationError("snapshot corridor must reference a published family")
            if (
                corridor.asset != self.asset
                or corridor.timeframe != self.timeframe
                or corridor.timestamp != self.timestamp
                or corridor.role is not family.current_role
                or corridor.model_version != self.model_version
                or corridor.config_version != self.config_version
                or corridor.resolved_config_hash != self.resolved_config_hash
            ):
                raise ContractValidationError("snapshot corridor identity must match its family and snapshot")
            if corridor.representative_member_id != family.representative_member_id:
                raise ContractValidationError("snapshot corridor representative must match its family")
            if not _interaction_close(
                corridor.representative_slope_per_second,
                family.representative.slope_per_second,
            ):
                raise ContractValidationError("snapshot corridor representative slope must match its exact rail")
            if set(corridor.ordered_member_ids) != {member.member_id for member in family.members}:
                raise ContractValidationError("snapshot corridor member IDs must match its family exactly")
            member_by_id = {member.member_id: member for member in family.members}
            expected_rails = tuple(
                sorted(
                    (
                        (
                            member.geometry.value_at(self.timestamp),
                            member.member_id,
                        )
                        for member in family.members
                    ),
                    key=lambda item: item,
                )
            )
            if tuple(corridor.ordered_member_ids) != tuple(item[1] for item in expected_rails):
                raise ContractValidationError("snapshot corridor rail ordering must match exact geometry")
            normalization_atr = _number(
                _mapping(self.diagnostics, field_name="diagnostics").get("normalization_atr"),
                field_name="diagnostics.normalization_atr",
                minimum=0.0,
            )
            if normalization_atr <= 0.0:
                raise ContractValidationError("snapshot corridor requires positive normalization ATR")
            for rail, (price, member_id) in zip(corridor.rails, expected_rails, strict=True):
                if rail.member_id != member_id or not _interaction_close(rail.projected_price, price):
                    raise ContractValidationError("snapshot corridor projected rail must match exact member geometry")
                expected_offset = (
                    rail.projected_price - corridor.center_price
                ) / normalization_atr
                if not _interaction_close(rail.offset_from_representative_atr, expected_offset):
                    raise ContractValidationError("snapshot corridor rail offset must match normalization ATR")
            if not _interaction_close(
                corridor.center_price,
                member_by_id[corridor.representative_member_id].geometry.value_at(self.timestamp),
            ):
                raise ContractValidationError("snapshot corridor center must use the exact representative rail")
            if not _interaction_close(corridor.lower_price, corridor.rails[0].projected_price):
                raise ContractValidationError("snapshot corridor lower bound must match its first rail")
            if not _interaction_close(corridor.upper_price, corridor.rails[-1].projected_price):
                raise ContractValidationError("snapshot corridor upper bound must match its last rail")
            if not _interaction_close(
                corridor.width_atr,
                corridor.width_absolute / normalization_atr,
            ):
                raise ContractValidationError("snapshot corridor width_atr must match normalization ATR")
            gaps = tuple(
                (corridor.rails[index + 1].projected_price - corridor.rails[index].projected_price)
                / normalization_atr
                for index in range(corridor.rail_count - 1)
            )
            if gaps:
                expected_max = max(gaps)
                expected_median = sorted(gaps)[len(gaps) // 2] if len(gaps) % 2 else (
                    sorted(gaps)[len(gaps) // 2 - 1] + sorted(gaps)[len(gaps) // 2]
                ) / 2.0
                mean_gap = sum(gaps) / len(gaps)
                variance = sum((gap - mean_gap) ** 2 for gap in gaps) / len(gaps)
                expected_stability = 1.0 / (
                    1.0 + math.sqrt(variance) / expected_median
                )
                if (
                    not _interaction_close(corridor.max_adjacent_gap_atr or 0.0, expected_max)
                    or not _interaction_close(corridor.median_adjacent_gap_atr or 0.0, expected_median)
                    or not _interaction_close(corridor.spacing_stability or 0.0, expected_stability)
                ):
                    raise ContractValidationError("snapshot corridor spacing diagnostics must match rail projections")
        if phase_g_marker:
            transition_by_family_id: dict[str, FamilyTransition] = {}
            for transition in transitions:
                if transition.family_id in transition_by_family_id:
                    raise ContractValidationError("Phase-G snapshot requires at most one transition per family")
                transition_by_family_id[transition.family_id] = transition
            published_family_ids = set(present_families)
            current_transition_family_ids = {
                transition.family_id
                for transition in transitions
                if transition.transition_type is not FamilyTransitionType.EXPIRE
            }
            if current_transition_family_ids != published_family_ids:
                raise ContractValidationError(
                    "Phase-G snapshot requires one current family transition per published family"
                )
            if any(transition.timestamp != self.timestamp for transition in transitions):
                raise ContractValidationError("Phase-G transition timestamp must match snapshot timestamp")
            if any(
                transition.source_group_id is None
                and transition.source_group_candidate_ids
                for transition in transitions
            ):
                raise ContractValidationError(
                    "Phase-G source group candidates require a source group audit"
                )
            source_group_by_id = {
                audit.source_group_id: audit for audit in source_group_audits
            }
            referenced_source_group_ids = {
                transition.source_group_id
                for transition in transitions
                if transition.source_group_id is not None
            }
            if set(source_group_by_id) != referenced_source_group_ids:
                raise ContractValidationError(
                    "Phase-G source group audits must exactly cover transition provenance"
                )
            for transition in transitions:
                family = present_families.get(transition.family_id)
                if transition.transition_type is FamilyTransitionType.EXPIRE:
                    if (
                        transition.current_rail_count != 0
                        or transition.current_representative_member_id is not None
                        or transition.added_member_ids
                        or transition.continued_member_ids
                    ):
                        raise ContractValidationError("EXPIRE transition cannot retain current rail evidence")
                    resulting_family_state = None
                else:
                    if family is None:  # Defensive: the generic boundary already rejects this.
                        raise ContractValidationError("Phase-G transition must reference a published family")
                    current_member_ids = {member.member_id for member in family.members}
                    audited_current_member_ids = set(transition.added_member_ids) | set(
                        transition.continued_member_ids
                    )
                    if transition.current_rail_count != len(family.members):
                        raise ContractValidationError("Phase-G transition current_rail_count must match its family")
                    if audited_current_member_ids != current_member_ids:
                        raise ContractValidationError("Phase-G transition membership audit must match its family")
                    if transition.current_representative_member_id != family.representative_member_id:
                        raise ContractValidationError("Phase-G transition representative must match its family")
                    if transition.transition_type is FamilyTransitionType.BIRTH:
                        if (
                            transition.previous_rail_count != 0
                            or transition.previous_representative_member_id is not None
                            or transition.continued_member_ids
                            or transition.removed_member_ids
                            or set(transition.added_member_ids) != current_member_ids
                        ):
                            raise ContractValidationError("Phase-G BIRTH transition audit must contain only added rails")
                    elif (
                        transition.previous_representative_member_id is None
                        or transition.current_representative_member_id is None
                    ):
                        raise ContractValidationError("Phase-G continuation transition requires representative evidence")
                    resulting_family_state = family.to_dict()
                    if transition.source_group_id is not None:
                        audit = source_group_by_id.get(transition.source_group_id)
                        if audit is None:
                            raise ContractValidationError("Phase-G transition source group audit is missing")
                        if (
                            audit.asset != self.asset
                            or audit.timeframe != self.timeframe
                            or audit.observed_at != self.timestamp
                            or audit.role is not family.current_role
                            or audit.model_version != self.model_version
                            or audit.config_version != self.config_version
                            or audit.resolved_config_hash != self.resolved_config_hash
                        ):
                            raise ContractValidationError(
                                "Phase-G source group audit identity must match snapshot and family"
                            )
                        if audit.candidate_ids != transition.source_group_candidate_ids:
                            raise ContractValidationError(
                                "Phase-G source group candidates must match transition provenance"
                            )
                    elif transition.source_group_candidate_ids:
                        raise ContractValidationError(
                            "Phase-G source group candidates require a source group audit"
                        )
                transition_payload = transition.to_dict()
                transition_payload.pop("transition_id")
                expected_transition_id = deterministic_id(
                    "family-transition",
                    {
                        "transition": transition_payload,
                        "resulting_family_state": resulting_family_state,
                    },
                )
                if transition.transition_id != expected_transition_id:
                    raise ContractValidationError("Phase-G transition_id must bind the audit and resulting family")
        if any(not isinstance(observation, FamilyInteractionObservation) for observation in observations):
            raise ContractValidationError("snapshot observations must use FamilyInteractionObservation")
        if len({observation.observation_id for observation in observations}) != len(observations):
            raise ContractValidationError("snapshot observation IDs must be unique")
        if len({observation.family_id for observation in observations}) != len(observations):
            raise ContractValidationError("snapshot observations must contain exactly one observation per family")
        if observations and tuple(sorted(observations, key=lambda item: (item.family_id, item.observation_id))) != observations:
            raise ContractValidationError("snapshot observations must have deterministic family ordering")
        if any(observation.timestamp != self.timestamp for observation in observations):
            raise ContractValidationError("snapshot observations must use the snapshot timestamp")
        if any(observation.family_id not in present_families for observation in observations):
            raise ContractValidationError("snapshot observations must reference published families")
        if observations and len(observations) != len(present_families):
            raise ContractValidationError("non-empty snapshot observations must cover every published family exactly once")
        if observations and {observation.family_id for observation in observations} != set(present_families):
            raise ContractValidationError("non-empty snapshot observations must cover every published family")
        for observation in observations:
            family = present_families[observation.family_id]
            exact_center = family.representative.value_at(self.timestamp)
            if observation.role is not family.current_role:
                raise ContractValidationError("snapshot observation role must match the published family role")
            if not _interaction_close(observation.exact_line_price, exact_center):
                raise ContractValidationError("snapshot observation exact line price must match the published representative")
            if not _interaction_close(observation.zone.center_price, exact_center):
                raise ContractValidationError("snapshot observation zone center must match the published representative")
            if observation.zone.line_id != family.family_id:
                raise ContractValidationError("snapshot observation zone must identify the published family")
        observation_by_id = {
            observation.observation_id: observation for observation in observations
        }
        if any(not isinstance(event, FamilyInteractionEvent) for event in interaction_events):
            raise ContractValidationError("snapshot interaction_events must use FamilyInteractionEvent")
        if len({event.event_id for event in interaction_events}) != len(interaction_events):
            raise ContractValidationError("snapshot interaction event IDs must be unique")
        if len({event.family_id for event in interaction_events}) != len(interaction_events):
            raise ContractValidationError("snapshot contains more than one interaction event per family")
        if interaction_events and tuple(sorted(interaction_events, key=lambda item: (item.family_id, item.event_id))) != interaction_events:
            raise ContractValidationError("snapshot interaction events must have deterministic family ordering")
        for event in interaction_events:
            family = present_families.get(event.family_id)
            if family is None:
                raise ContractValidationError("snapshot interaction event must reference a published family")
            if event.asset != self.asset or event.timeframe != self.timeframe:
                raise ContractValidationError("snapshot interaction event asset/timeframe mismatch")
            if event.model_version != self.model_version or event.config_version != self.config_version or event.resolved_config_hash != self.resolved_config_hash:
                raise ContractValidationError("snapshot interaction event metadata must match the snapshot")
            if event.updated_at > self.timestamp:
                raise ContractValidationError("snapshot interaction event timestamp cannot exceed snapshot timestamp")
            if event.current_event_role is not family.current_role:
                raise ContractValidationError("snapshot interaction event role must match the published family")
            if (
                family.lifecycle_state is FamilyLifecycleState.DORMANT
                and event.state is InteractionEventState.ROLE_REVERSED
            ):
                raise ContractValidationError(
                    "dormant family cannot retain a ROLE_REVERSED interaction event"
                )
            if (
                family.lifecycle_state is FamilyLifecycleState.ACTIVE
                and event.updated_at == self.timestamp
            ):
                observation = observation_by_id.get(event.last_observation_id)
                if observation is None or observation.family_id != event.family_id:
                    raise ContractValidationError(
                        "active current event must reference its current family observation"
                    )
        if any(not isinstance(transition, FamilyInteractionEventTransition) for transition in interaction_event_transitions):
            raise ContractValidationError("snapshot interaction event transitions must use canonical contracts")
        if len({transition.transition_id for transition in interaction_event_transitions}) != len(interaction_event_transitions):
            raise ContractValidationError("snapshot interaction event transition IDs must be unique")
        if interaction_event_transitions and tuple(sorted(interaction_event_transitions, key=lambda item: (item.event_id, item.transition_id))) != interaction_event_transitions:
            raise ContractValidationError("snapshot interaction event transitions must have deterministic ordering")
        event_by_id = {event.event_id: event for event in interaction_events}
        transitions_by_event_id: dict[str, list[FamilyInteractionEventTransition]] = {}
        for transition in interaction_event_transitions:
            transitions_by_event_id.setdefault(transition.event_id, []).append(transition)
        for event in interaction_events:
            event_transitions = transitions_by_event_id.get(event.event_id, [])
            if event.updated_at != self.timestamp:
                if event_transitions:
                    raise ContractValidationError(
                        "frozen interaction event cannot include a current transition"
                    )
                continue
            if event.previous_state is None:
                if event_transitions:
                    raise ContractValidationError(
                        "new interaction episode cannot include a transition"
                    )
                continue
            if event.previous_state is event.state:
                if event_transitions:
                    raise ContractValidationError(
                        "unchanged interaction event cannot include a transition"
                    )
                continue
            if len(event_transitions) != 1:
                raise ContractValidationError(
                    "changed interaction event requires exactly one transition"
                )
        for transition in interaction_event_transitions:
            event = event_by_id.get(transition.event_id)
            if event is None:
                raise ContractValidationError("snapshot interaction event transition must reference a persisted event")
            if transition.family_id != event.family_id:
                raise ContractValidationError("event transition family must match its event")
            observation = observation_by_id.get(transition.trigger_observation_id)
            if observation is None or observation.family_id != event.family_id:
                raise ContractValidationError("event transition must reference an observation for the same family")
            if observation.close_price is None:
                raise ContractValidationError(
                    "event transition requires persisted close_price evidence"
                )
            if transition.timestamp > self.timestamp:
                raise ContractValidationError("event transition timestamp cannot exceed snapshot timestamp")
            if transition.model_version != self.model_version or transition.config_version != self.config_version or transition.resolved_config_hash != self.resolved_config_hash:
                raise ContractValidationError("event transition metadata must match the containing snapshot")
            if transition.to_state is not event.state:
                raise ContractValidationError("event transition target must match the persisted event state")
            if transition.from_state is not event.previous_state:
                raise ContractValidationError("event transition source must match the persisted previous state")
            if transition.timestamp != event.updated_at:
                raise ContractValidationError("event transition timestamp must match the persisted event update")
            if transition.trigger_observation_id != event.last_observation_id:
                raise ContractValidationError("event transition observation must match the persisted event")
            # Local import prevents a module cycle while keeping the state
            # table in its dedicated Phase-F lifecycle module.
            from .events import is_allowed_event_transition

            if not is_allowed_event_transition(transition.from_state, transition.to_state):
                raise ContractValidationError(
                    "snapshot contains a forbidden interaction event transition: "
                    f"{transition.from_state.value}->{transition.to_state.value}"
                )
        for event in interaction_events:
            family = present_families[event.family_id]
            if (
                family.lifecycle_state is FamilyLifecycleState.ACTIVE
                and event.updated_at == self.timestamp
            ):
                observation = observation_by_id[event.last_observation_id]
                if observation.close_price is None:
                    raise ContractValidationError(
                        "active current interaction event requires persisted close_price evidence"
                    )
        diagnostics = _freeze_mapping(self.diagnostics, field_name="diagnostics")
        interaction_diagnostic_keys = (
            "interaction_atr",
            "interaction_atr_method",
            "interaction_atr_sample_count",
            "interaction_observation_count",
        )
        present_interaction_diagnostic_keys = tuple(
            key for key in interaction_diagnostic_keys if key in diagnostics
        )
        if observations:
            reference_observation = observations[0]
            for observation in observations[1:]:
                if not _interaction_close(observation.interaction_atr, reference_observation.interaction_atr):
                    raise ContractValidationError("snapshot observations must use one interaction ATR value")
                if observation.interaction_atr_method != reference_observation.interaction_atr_method:
                    raise ContractValidationError("snapshot observations must use one interaction ATR method")
                if observation.interaction_atr_sample_count != reference_observation.interaction_atr_sample_count:
                    raise ContractValidationError("snapshot observations must use one interaction ATR sample count")
            diagnostic_atr = _number(diagnostics.get("interaction_atr"), field_name="diagnostics.interaction_atr", minimum=0.0)
            if diagnostic_atr <= 0.0 or not _interaction_close(diagnostic_atr, reference_observation.interaction_atr):
                raise ContractValidationError("snapshot interaction_atr diagnostic must match observations")
            if diagnostics.get("interaction_atr_method") != reference_observation.interaction_atr_method:
                raise ContractValidationError("snapshot interaction_atr_method diagnostic must match observations")
            if _integer(
                diagnostics.get("interaction_atr_sample_count"),
                field_name="diagnostics.interaction_atr_sample_count",
                minimum=1,
            ) != reference_observation.interaction_atr_sample_count:
                raise ContractValidationError("snapshot interaction_atr_sample_count diagnostic must match observations")
            if _integer(
                diagnostics.get("interaction_observation_count"),
                field_name="diagnostics.interaction_observation_count",
            ) != len(observations):
                raise ContractValidationError("snapshot interaction_observation_count diagnostic must match observations")
        elif present_interaction_diagnostic_keys:
            if set(present_interaction_diagnostic_keys) != set(interaction_diagnostic_keys):
                raise ContractValidationError(
                    "empty snapshot observations require either no interaction diagnostics or the complete empty set"
                )
            if _integer(
                diagnostics["interaction_observation_count"],
                field_name="diagnostics.interaction_observation_count",
            ) != 0:
                raise ContractValidationError(
                    "empty snapshot observations require interaction_observation_count equal to zero"
                )
            if any(
                diagnostics[key] is not None
                for key in (
                    "interaction_atr",
                    "interaction_atr_method",
                    "interaction_atr_sample_count",
                )
            ):
                raise ContractValidationError(
                    "empty snapshot observations require null interaction ATR diagnostics"
                )
        object.__setattr__(self, "active_families", active_families)
        object.__setattr__(self, "dormant_families", dormant_families)
        object.__setattr__(self, "transitions", transitions)
        object.__setattr__(self, "source_group_audits", source_group_audits)
        object.__setattr__(self, "corridors", corridors)
        object.__setattr__(self, "observations", observations)
        object.__setattr__(self, "interaction_events", interaction_events)
        object.__setattr__(self, "interaction_event_transitions", interaction_event_transitions)
        object.__setattr__(self, "diagnostics", diagnostics)
        validate_trendline_family_snapshot_identity(self)

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrendlineFamilySnapshot":
        return _decode("TrendlineFamilySnapshot", value, lambda item: cls(
            snapshot_id=_required(item, "snapshot_id", owner="TrendlineFamilySnapshot"), asset=_required(item, "asset", owner="TrendlineFamilySnapshot"),
            timeframe=_required(item, "timeframe", owner="TrendlineFamilySnapshot"), timestamp=parse_utc_isoformat(_required(item, "timestamp", owner="TrendlineFamilySnapshot")),
            previous_snapshot_id=item.get("previous_snapshot_id"), model_version=_required(item, "model_version", owner="TrendlineFamilySnapshot"),
            config_version=_required(item, "config_version", owner="TrendlineFamilySnapshot"), resolved_config_hash=_required(item, "resolved_config_hash", owner="TrendlineFamilySnapshot"),
            active_families=tuple(TrendlineFamilyState.from_dict(family) for family in _required(item, "active_families", owner="TrendlineFamilySnapshot")),
            dormant_families=tuple(TrendlineFamilyState.from_dict(family) for family in _required(item, "dormant_families", owner="TrendlineFamilySnapshot")),
            transitions=tuple(FamilyTransition.from_dict(transition) for transition in _required(item, "transitions", owner="TrendlineFamilySnapshot")),
            source_group_audits=tuple(
                FamilySourceGroupAudit.from_dict(audit)
                for audit in item.get("source_group_audits", ())
            ),
            corridors=tuple(FamilyCorridor.from_dict(corridor) for corridor in item.get("corridors", ())),
            observations=tuple(FamilyInteractionObservation.from_dict(observation) for observation in item.get("observations", ())),
            interaction_events=tuple(FamilyInteractionEvent.from_dict(event) for event in item.get("interaction_events", ())),
            interaction_event_transitions=tuple(FamilyInteractionEventTransition.from_dict(transition) for transition in item.get("interaction_event_transitions", ())),
            diagnostics=item.get("diagnostics", {}),
        ))


def trendline_family_snapshot_identity_payload(
    *,
    asset: str,
    timeframe: str,
    timestamp: datetime,
    previous_snapshot_id: str | None,
    model_version: str,
    config_version: str,
    resolved_config_hash: str,
    active_families: tuple[TrendlineFamilyState, ...],
    dormant_families: tuple[TrendlineFamilyState, ...],
    transitions: tuple[FamilyTransition, ...],
    source_group_audits: tuple[FamilySourceGroupAudit, ...],
    corridors: tuple[FamilyCorridor, ...],
    observations: tuple[FamilyInteractionObservation, ...],
    interaction_events: tuple[FamilyInteractionEvent, ...],
    interaction_event_transitions: tuple[FamilyInteractionEventTransition, ...],
    diagnostics: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Return canonical Phase-G snapshot identity inputs, excluding snapshot_id."""

    return {
        "asset": asset,
        "timeframe": timeframe,
        "timestamp": timestamp,
        "previous_snapshot_id": previous_snapshot_id,
        "model_version": model_version,
        "config_version": config_version,
        "resolved_config_hash": resolved_config_hash,
        "active_families": active_families,
        "dormant_families": dormant_families,
        "transitions": transitions,
        "source_group_audits": source_group_audits,
        "corridors": corridors,
        "observations": observations,
        "interaction_events": interaction_events,
        "interaction_event_transitions": interaction_event_transitions,
        "diagnostics": diagnostics,
    }


def compute_trendline_family_snapshot_id(
    **identity_inputs: Any,
) -> str:
    """Compute canonical content-addressed identity for a complete Phase-G snapshot."""

    return deterministic_id(
        "family-snapshot",
        trendline_family_snapshot_identity_payload(**identity_inputs),
    )


def trendline_family_snapshot_has_phase_g_evidence(
    snapshot: TrendlineFamilySnapshot,
) -> bool:
    """Classify Phase-G payloads from immutable structural evidence and marker."""

    diagnostics = snapshot.diagnostics
    if diagnostics.get("rail_grouping_enabled") is True:
        return True
    if snapshot.source_group_audits or snapshot.corridors:
        return True
    if any(
        len(family.members) > 1
        for family in snapshot.active_families + snapshot.dormant_families
    ):
        return True
    if any(
        transition.added_member_ids
        or transition.continued_member_ids
        or transition.removed_member_ids
        or transition.previous_representative_member_id is not None
        or transition.current_representative_member_id is not None
        or transition.previous_rail_count > 0
        or transition.current_rail_count > 0
        or transition.source_group_id is not None
        or transition.source_group_candidate_ids
        for transition in snapshot.transitions
    ):
        return True
    return any(key in diagnostics for key in _PHASE_G_DIAGNOSTIC_KEYS)


def validate_trendline_family_snapshot_identity(snapshot: TrendlineFamilySnapshot) -> None:
    """Require a canonical aggregate ID only for Phase-G snapshot payloads."""

    if not trendline_family_snapshot_has_phase_g_evidence(snapshot):
        return
    if snapshot.diagnostics.get("rail_grouping_enabled") is not True:
        raise ContractValidationError(
            "Phase-G evidence requires diagnostics.rail_grouping_enabled=True"
        )
    expected_snapshot_id = compute_trendline_family_snapshot_id(
        asset=snapshot.asset,
        timeframe=snapshot.timeframe,
        timestamp=snapshot.timestamp,
        previous_snapshot_id=snapshot.previous_snapshot_id,
        model_version=snapshot.model_version,
        config_version=snapshot.config_version,
        resolved_config_hash=snapshot.resolved_config_hash,
        active_families=snapshot.active_families,
        dormant_families=snapshot.dormant_families,
        transitions=snapshot.transitions,
        source_group_audits=snapshot.source_group_audits,
        corridors=snapshot.corridors,
        observations=snapshot.observations,
        interaction_events=snapshot.interaction_events,
        interaction_event_transitions=snapshot.interaction_event_transitions,
        diagnostics=snapshot.diagnostics,
    )
    if snapshot.snapshot_id != expected_snapshot_id:
        raise ContractValidationError(
            "Phase-G snapshot_id must bind the complete snapshot payload"
        )


@dataclass(frozen=True)
class TrendlineFamilyOutput:
    snapshot: TrendlineFamilySnapshot
    ranked_support_families: tuple[str, ...]
    ranked_resistance_families: tuple[str, ...]
    nearest_support_family_id: str | None
    nearest_resistance_family_id: str | None
    features: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, TrendlineFamilySnapshot):
            raise ContractValidationError("output snapshot must use TrendlineFamilySnapshot")
        object.__setattr__(self, "ranked_support_families", _tuple_of_strings(self.ranked_support_families, field_name="ranked_support_families"))
        object.__setattr__(self, "ranked_resistance_families", _tuple_of_strings(self.ranked_resistance_families, field_name="ranked_resistance_families"))
        object.__setattr__(self, "nearest_support_family_id", _optional_string(self.nearest_support_family_id, field_name="nearest_support_family_id"))
        object.__setattr__(self, "nearest_resistance_family_id", _optional_string(self.nearest_resistance_family_id, field_name="nearest_resistance_family_id"))
        object.__setattr__(self, "features", _freeze_mapping(self.features, field_name="features"))

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrendlineFamilyOutput":
        return _decode("TrendlineFamilyOutput", value, lambda item: cls(
            snapshot=TrendlineFamilySnapshot.from_dict(_required(item, "snapshot", owner="TrendlineFamilyOutput")),
            ranked_support_families=tuple(_required(item, "ranked_support_families", owner="TrendlineFamilyOutput")),
            ranked_resistance_families=tuple(_required(item, "ranked_resistance_families", owner="TrendlineFamilyOutput")),
            nearest_support_family_id=item.get("nearest_support_family_id"), nearest_resistance_family_id=item.get("nearest_resistance_family_id"), features=item.get("features", {}),
        ))
