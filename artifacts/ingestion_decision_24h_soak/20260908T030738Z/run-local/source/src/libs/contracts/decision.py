"""Pure semantic contracts for the future :mod:`decision_app` model boundary.

This module intentionally knows nothing about storage, transport, services, or
runtime orchestration.  It is the small contract surface that a model plugin may
depend on.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from math import isfinite
from types import MappingProxyType
from typing import Any, Literal, Protocol, TypeVar, runtime_checkable

Alignment = Literal["exact", "at_or_before", "bounded_window"]
DataMode = Literal["LIVE", "REPLAY"]
ResolvedCapability = Literal["LIVE_AND_REPLAY", "LIVE_ONLY", "UNAVAILABLE"]
ModelOutputKind = Literal["analytical", "predictive", "decision_capable"]
DirectionHint = Literal[-1, 0, 1]
ModelState = object | None

_KT = TypeVar("_KT")
_VT = TypeVar("_VT")


class FrozenMapping(Mapping[_KT, _VT]):
    """A small immutable mapping used at plugin-visible boundaries."""

    __slots__ = ("_data",)

    def __init__(self, values: Mapping[_KT, _VT] | None = None) -> None:
        object.__setattr__(self, "_data", MappingProxyType(dict(values or {})))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("FrozenMapping is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("FrozenMapping is immutable")

    def __getitem__(self, key: _KT) -> _VT:
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"FrozenMapping({dict(self._data)!r})"


def deep_freeze(value: Any) -> Any:
    """Return an immutable snapshot of the supported semantic-value vocabulary.

    Supported values are scalar standard-library values, UTC datetimes,
    timedeltas, string-keyed mappings, and lists/tuples. Recursive containers
    are frozen into ``FrozenMapping``/``tuple`` so freezing the outer dataclass
    cannot leave a mutable nested escape hatch. Unsupported custom/mutable
    objects and cyclic containers are rejected instead of being passed through.
    """

    return _deep_freeze(value, active=set())


def freeze_model_state(value: ModelState) -> ModelState:
    """Freeze an opaque model state before supplying it to a plugin."""

    return deep_freeze(value)


def _deep_freeze(value: Any, *, active: set[int]) -> Any:
    if isinstance(
        value, (str, bytes, bool, int, float, Decimal, datetime, timedelta, type(None))
    ):
        if isinstance(value, float) and not isfinite(value):
            raise ValueError("non-finite floats are not supported in semantic values")
        if isinstance(value, Decimal) and not value.is_finite():
            raise ValueError("non-finite Decimals are not supported in semantic values")
        if isinstance(value, datetime):
            require_utc(value, field_name="semantic datetime")
        return value

    object_id = id(value)
    if isinstance(value, FrozenMapping):
        if object_id in active:
            raise ValueError("cyclic mappings are not supported in semantic contracts")
        active.add(object_id)
        try:
            if any(not isinstance(key, str) for key in value):
                raise TypeError("semantic mappings require string keys")
            return FrozenMapping(
                {key: _deep_freeze(item, active=active) for key, item in value.items()}
            )
        finally:
            active.remove(object_id)

    if isinstance(value, Mapping):
        if object_id in active:
            raise ValueError("cyclic mappings are not supported in semantic contracts")
        active.add(object_id)
        try:
            if any(not isinstance(key, str) for key in value):
                raise TypeError("semantic mappings require string keys")
            return FrozenMapping(
                {key: _deep_freeze(item, active=active) for key, item in value.items()}
            )
        finally:
            active.remove(object_id)

    if isinstance(value, (list, tuple)):
        if object_id in active:
            raise ValueError("cyclic sequences are not supported in semantic contracts")
        active.add(object_id)
        try:
            return tuple(_deep_freeze(item, active=active) for item in value)
        finally:
            active.remove(object_id)

    raise TypeError(
        "unsupported mutable or custom value in semantic contract: "
        f"{type(value).__name__}"
    )


def require_utc(value: object, *, field_name: str) -> datetime:
    """Require an aware UTC datetime; never infer units or convert offsets."""

    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def _require_non_empty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _require_bool(value: object, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a bool")
    return value


def _require_finite_decimal(value: object, *, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return value


def _require_non_negative_duration(value: timedelta | None, *, field_name: str) -> None:
    if value is not None and not isinstance(value, timedelta):
        raise TypeError(f"{field_name} must be a timedelta or None")
    if value is not None and value < timedelta(0):
        raise ValueError(f"{field_name} must be non-negative")


def _freeze_string_mapping(
    value: Mapping[str, Any], *, field_name: str
) -> FrozenMapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    return FrozenMapping({key: deep_freeze(item) for key, item in value.items()})


def _normalize_strings(values: Sequence[str], *, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} must be a sequence of strings")
    normalized = tuple(
        _require_non_empty(item, field_name=field_name) for item in values
    )
    return normalized


@dataclass(frozen=True, slots=True, kw_only=True)
class CausalBarView:
    """One precision-preserving canonical bar at an explicit causal cutoff."""

    timeframe: str
    bar_open_at: datetime
    bar_close_at: datetime
    market_as_of: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    taker_buy_base: Decimal | None
    closed: bool

    def __post_init__(self) -> None:
        _require_non_empty(self.timeframe, field_name="timeframe")
        if not isinstance(self.closed, bool):
            raise TypeError("closed must be a bool")
        require_utc(self.bar_open_at, field_name="bar_open_at")
        require_utc(self.bar_close_at, field_name="bar_close_at")
        require_utc(self.market_as_of, field_name="market_as_of")
        if self.bar_close_at <= self.bar_open_at:
            raise ValueError("bar_close_at must be after bar_open_at")
        if not self.bar_open_at < self.market_as_of <= self.bar_close_at:
            raise ValueError(
                "market_as_of must be after bar_open_at and at or before bar_close_at"
            )
        if self.closed and self.market_as_of != self.bar_close_at:
            raise ValueError("closed bars require market_as_of == bar_close_at")
        if not self.closed and self.market_as_of >= self.bar_close_at:
            raise ValueError("projected bars require market_as_of < bar_close_at")

        open_price = _require_finite_decimal(self.open, field_name="open")
        high = _require_finite_decimal(self.high, field_name="high")
        low = _require_finite_decimal(self.low, field_name="low")
        close = _require_finite_decimal(self.close, field_name="close")
        volume = _require_finite_decimal(self.volume, field_name="volume")
        if self.taker_buy_base is not None:
            taker_buy_base = _require_finite_decimal(
                self.taker_buy_base,
                field_name="taker_buy_base",
            )
        else:
            taker_buy_base = None

        if low > high:
            raise ValueError("low must be less than or equal to high")
        if not low <= open_price <= high:
            raise ValueError("open must be between low and high")
        if not low <= close <= high:
            raise ValueError("close must be between low and high")
        if volume < 0:
            raise ValueError("volume must be non-negative")
        if taker_buy_base is not None and not 0 <= taker_buy_base <= volume:
            raise ValueError("taker_buy_base must be between zero and volume")


@dataclass(frozen=True, slots=True, kw_only=True)
class FeatureRequirement:
    """Model-owned semantic demand for one shared feature."""

    name: str
    required: bool = True

    def __post_init__(self) -> None:
        _require_non_empty(self.name, field_name="feature name")
        _require_bool(self.required, field_name="feature required")


@dataclass(frozen=True, slots=True, kw_only=True)
class DataRequirement:
    """Model-declared semantic demand, without physical source ownership."""

    concept: str
    required: bool = True
    replay_support_required: bool = False
    max_age_at_market_as_of: timedelta | None = None
    max_available_lag: timedelta | None = None
    alignment: Alignment = "at_or_before"

    def __post_init__(self) -> None:
        _require_non_empty(self.concept, field_name="concept")
        _require_bool(self.required, field_name="required")
        _require_bool(
            self.replay_support_required,
            field_name="replay_support_required",
        )
        if self.alignment not in {"exact", "at_or_before", "bounded_window"}:
            raise ValueError("alignment is not supported")
        _require_non_negative_duration(
            self.max_age_at_market_as_of,
            field_name="max_age_at_market_as_of",
        )
        _require_non_negative_duration(
            self.max_available_lag, field_name="max_available_lag"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DataRequest:
    """Runtime-materialized semantic request for one evaluation cutoff."""

    request_key: str
    concept: str
    market_as_of: datetime
    required: bool = True
    mode: DataMode
    resolver_knowledge_cutoff: datetime
    replay_support_required: bool = False
    asset: str | None = None
    scope: str | None = None
    freshness_bound: timedelta | None = None
    max_available_lag: timedelta | None = None
    alignment: Alignment = "at_or_before"

    def __post_init__(self) -> None:
        _require_non_empty(self.request_key, field_name="request_key")
        _require_non_empty(self.concept, field_name="concept")
        _require_bool(self.required, field_name="required")
        _require_bool(
            self.replay_support_required,
            field_name="replay_support_required",
        )
        require_utc(self.market_as_of, field_name="market_as_of")
        if self.mode not in {"LIVE", "REPLAY"}:
            raise ValueError("mode must be LIVE or REPLAY")
        require_utc(
            self.resolver_knowledge_cutoff,
            field_name="resolver_knowledge_cutoff",
        )
        if self.resolver_knowledge_cutoff < self.market_as_of:
            raise ValueError(
                "resolver_knowledge_cutoff must be at or after market_as_of"
            )
        if self.asset is not None:
            _require_non_empty(self.asset, field_name="asset")
        if self.scope is not None:
            _require_non_empty(self.scope, field_name="scope")
        _require_non_negative_duration(
            self.freshness_bound, field_name="freshness_bound"
        )
        _require_non_negative_duration(
            self.max_available_lag,
            field_name="max_available_lag",
        )
        if self.alignment not in {"exact", "at_or_before", "bounded_window"}:
            raise ValueError("alignment is not supported")


@dataclass(frozen=True, slots=True, kw_only=True)
class DataSnapshot:
    """Resolved external observation with explicit point-in-time provenance."""

    request_key: str
    concept: str
    payload: Any
    event_time: datetime
    available_at: datetime
    fetched_at: datetime
    source: str
    resolved_capability: ResolvedCapability
    represented_end_at: datetime | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.request_key, field_name="request_key")
        _require_non_empty(self.concept, field_name="concept")
        require_utc(self.event_time, field_name="event_time")
        require_utc(self.available_at, field_name="available_at")
        require_utc(self.fetched_at, field_name="fetched_at")
        _require_non_empty(self.source, field_name="source")
        if self.resolved_capability not in {
            "LIVE_AND_REPLAY",
            "LIVE_ONLY",
            "UNAVAILABLE",
        }:
            raise ValueError("resolved_capability is not supported")
        if self.represented_end_at is not None:
            require_utc(self.represented_end_at, field_name="represented_end_at")
        object.__setattr__(self, "payload", deep_freeze(self.payload))
        object.__setattr__(
            self,
            "provenance",
            _freeze_string_mapping(self.provenance, field_name="provenance"),
        )

    def validate_against(self, request: DataRequest) -> DataSnapshot:
        return validate_data_snapshot(request, self)


@dataclass(frozen=True, slots=True, kw_only=True)
class FeatureSnapshot:
    """Immutable plugin-visible result for one shared feature evaluation."""

    name: str
    version: str
    market_as_of: datetime
    value: Any
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.name, field_name="feature name")
        _require_non_empty(self.version, field_name="feature version")
        require_utc(self.market_as_of, field_name="feature market_as_of")
        object.__setattr__(self, "value", deep_freeze(self.value))
        object.__setattr__(
            self,
            "provenance",
            _freeze_string_mapping(self.provenance, field_name="feature provenance"),
        )


def validate_data_snapshot(
    request: DataRequest, snapshot: DataSnapshot
) -> DataSnapshot:
    """Validate a resolved snapshot against the request's PIT cutoff."""

    if snapshot.request_key != request.request_key:
        raise ValueError("snapshot request_key does not match request")
    if snapshot.concept != request.concept:
        raise ValueError("snapshot concept does not match request")
    if snapshot.event_time > request.market_as_of:
        raise ValueError("future snapshot event_time cannot be after market_as_of")
    if (
        snapshot.represented_end_at is not None
        and snapshot.represented_end_at > request.market_as_of
    ):
        raise ValueError("represented snapshot window cannot extend past market_as_of")
    if snapshot.available_at > request.resolver_knowledge_cutoff:
        raise ValueError(
            "snapshot available_at cannot be after resolver knowledge cutoff"
        )
    if snapshot.resolved_capability == "UNAVAILABLE":
        raise ValueError("UNAVAILABLE snapshots cannot satisfy data requests")
    if (
        request.mode == "REPLAY" or request.replay_support_required
    ) and snapshot.resolved_capability != "LIVE_AND_REPLAY":
        raise ValueError("REPLAY requires a LIVE_AND_REPLAY resolved capability")
    effective_observation_end = snapshot.represented_end_at or snapshot.event_time
    if (
        request.alignment == "exact"
        and effective_observation_end != request.market_as_of
    ):
        raise ValueError("snapshot observation does not satisfy exact alignment")
    if request.alignment == "bounded_window" and snapshot.represented_end_at is None:
        raise ValueError("bounded_window alignment requires represented_end_at")
    if (
        request.freshness_bound is not None
        and request.market_as_of - effective_observation_end > request.freshness_bound
    ):
        raise ValueError("snapshot observation is outside freshness bound")
    if request.max_available_lag is not None:
        if snapshot.available_at < effective_observation_end:
            raise ValueError("snapshot available_at precedes observation end")
        if (
            snapshot.available_at - effective_observation_end
            > request.max_available_lag
        ):
            raise ValueError("snapshot availability lag exceeds maximum")
    return snapshot


@dataclass(frozen=True, slots=True, kw_only=True)
class WarmupRequirements:
    """Small typed warmup requirement covering multiple timeframes."""

    bars_by_timeframe: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.bars_by_timeframe, Mapping):
            raise TypeError("bars_by_timeframe must be a mapping")
        normalized: dict[str, int] = {}
        for timeframe, bars in self.bars_by_timeframe.items():
            _require_non_empty(timeframe, field_name="timeframe")
            if isinstance(bars, bool) or not isinstance(bars, int) or bars < 0:
                raise ValueError("warmup bar counts must be non-negative integers")
            normalized[timeframe] = bars
        object.__setattr__(self, "bars_by_timeframe", FrozenMapping(normalized))


@dataclass(frozen=True, slots=True, kw_only=True)
class StateReconstructionRequirement:
    """Intrinsic state-reconstruction guarantee required by stateful plugins."""

    durable_pit_required: bool = True

    def __post_init__(self) -> None:
        _require_bool(self.durable_pit_required, field_name="durable_pit_required")


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelDependencyRequirement:
    """One model-owned dependency slot and its required artifact type."""

    slot_name: str
    artifact_type: str

    def __post_init__(self) -> None:
        _require_non_empty(self.slot_name, field_name="slot_name")
        _require_non_empty(self.artifact_type, field_name="artifact_type")


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelSpec:
    """Intrinsic plugin semantics, independent of asset configuration/policy."""

    name: str
    version: str
    stateful: bool
    output_kind: ModelOutputKind
    produces_artifact_type: str
    supported_trigger_modes: tuple[str, ...] = ()
    supported_timeframes: tuple[str, ...] = ()
    supported_trigger_timeframes: tuple[str, ...] = ()
    intrinsic_feature_requirements: tuple[FeatureRequirement, ...] = ()
    intrinsic_data_requirements: tuple[DataRequirement, ...] = ()
    dependency_requirements: tuple[ModelDependencyRequirement, ...] = ()
    warmup_requirements: WarmupRequirements = field(default_factory=WarmupRequirements)
    state_reconstruction: StateReconstructionRequirement = field(
        default_factory=StateReconstructionRequirement
    )

    def __post_init__(self) -> None:
        _require_non_empty(self.name, field_name="name")
        _require_non_empty(self.version, field_name="version")
        if not isinstance(self.stateful, bool):
            raise TypeError("stateful must be a bool")
        if self.output_kind not in {"analytical", "predictive", "decision_capable"}:
            raise ValueError("output_kind is not supported")
        _require_non_empty(
            self.produces_artifact_type,
            field_name="produces_artifact_type",
        )
        object.__setattr__(
            self,
            "supported_trigger_modes",
            _normalize_strings(
                self.supported_trigger_modes, field_name="supported_trigger_modes"
            ),
        )
        object.__setattr__(
            self,
            "supported_timeframes",
            _normalize_strings(
                self.supported_timeframes, field_name="supported_timeframes"
            ),
        )
        object.__setattr__(
            self,
            "supported_trigger_timeframes",
            _normalize_strings(
                self.supported_trigger_timeframes,
                field_name="supported_trigger_timeframes",
            ),
        )
        feature_requirements = tuple(self.intrinsic_feature_requirements)
        if any(
            not isinstance(item, FeatureRequirement) for item in feature_requirements
        ):
            raise TypeError(
                "intrinsic_feature_requirements must contain FeatureRequirement values"
            )
        feature_names = [item.name for item in feature_requirements]
        if len(set(feature_names)) != len(feature_names):
            raise ValueError("intrinsic feature requirement names must be unique")
        object.__setattr__(
            self,
            "intrinsic_feature_requirements",
            tuple(sorted(feature_requirements, key=lambda item: item.name)),
        )
        requirements = tuple(self.intrinsic_data_requirements)
        if any(not isinstance(item, DataRequirement) for item in requirements):
            raise TypeError(
                "intrinsic_data_requirements must contain DataRequirement values"
            )
        data_concepts = [item.concept for item in requirements]
        if len(set(data_concepts)) != len(data_concepts):
            raise ValueError("intrinsic data requirement concepts must be unique")
        object.__setattr__(
            self,
            "intrinsic_data_requirements",
            tuple(sorted(requirements, key=lambda item: item.concept)),
        )
        dependencies = tuple(self.dependency_requirements)
        if any(
            not isinstance(item, ModelDependencyRequirement) for item in dependencies
        ):
            raise TypeError(
                "dependency_requirements must contain ModelDependencyRequirement values"
            )
        dependency_slots = [item.slot_name for item in dependencies]
        if len(set(dependency_slots)) != len(dependency_slots):
            raise ValueError("dependency_requirements slot names must be unique")
        object.__setattr__(self, "dependency_requirements", dependencies)
        if self.stateful:
            if not self.state_reconstruction.durable_pit_required:
                raise ValueError("stateful models require durable PIT reconstruction")
            if any(not item.replay_support_required for item in requirements):
                raise ValueError(
                    "stateful models require replay support for every data input"
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelArtifact:
    """Typed analytical output; it intentionally carries no direction field."""

    binding_id: str
    lane_id: str
    asset: str
    decision_timeframe: str
    trigger_timeframe: str
    market_as_of: datetime
    artifact_type: str
    value: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "binding_id",
            "lane_id",
            "asset",
            "decision_timeframe",
            "trigger_timeframe",
            "artifact_type",
        ):
            _require_non_empty(getattr(self, field_name), field_name=field_name)
        require_utc(self.market_as_of, field_name="market_as_of")
        object.__setattr__(self, "value", deep_freeze(self.value))
        object.__setattr__(
            self,
            "metadata",
            _freeze_string_mapping(self.metadata, field_name="metadata"),
        )
        object.__setattr__(
            self,
            "provenance",
            _freeze_string_mapping(self.provenance, field_name="provenance"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelDecision:
    """Optional direction-bearing model output with explicit market identity."""

    binding_id: str
    asset: str
    decision_timeframe: str
    trigger_timeframe: str
    market_as_of: datetime
    signal_time: datetime
    direction_hint: DirectionHint | None = None
    score: float | None = None
    conviction: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "binding_id",
            "asset",
            "decision_timeframe",
            "trigger_timeframe",
        ):
            _require_non_empty(getattr(self, field_name), field_name=field_name)
        require_utc(self.market_as_of, field_name="market_as_of")
        require_utc(self.signal_time, field_name="signal_time")
        if self.signal_time != self.market_as_of:
            raise ValueError("signal_time must equal market_as_of")
        if isinstance(self.direction_hint, bool) or self.direction_hint not in {
            -1,
            0,
            1,
            None,
        }:
            raise ValueError("direction_hint must be -1, 0, 1, or None")
        if self.score is not None:
            if isinstance(self.score, bool) or not isinstance(
                self.score, (int, float, Decimal)
            ):
                raise TypeError("score must be a finite numeric value")
            if not isfinite(float(self.score)):
                raise ValueError("score must be finite")
            object.__setattr__(self, "score", float(self.score))
        if self.conviction is not None:
            if isinstance(self.conviction, bool) or not isinstance(
                self.conviction,
                (int, float, Decimal),
            ):
                raise TypeError("conviction must be a finite numeric value")
            conviction = float(self.conviction)
            if not isfinite(conviction) or not 0.0 <= conviction <= 1.0:
                raise ValueError("conviction must be finite and between zero and one")
            object.__setattr__(self, "conviction", conviction)
        object.__setattr__(
            self,
            "metadata",
            _freeze_string_mapping(self.metadata, field_name="metadata"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelOutcome:
    """Plugin result containing an artifact and optional trade decision."""

    artifact: ModelArtifact
    decision: ModelDecision | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    proposed_next_state: ModelState = None

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, ModelArtifact):
            raise TypeError("artifact must be a ModelArtifact")
        if self.decision is not None and not isinstance(self.decision, ModelDecision):
            raise TypeError("decision must be a ModelDecision or None")
        if self.decision is not None:
            if self.decision.binding_id != self.artifact.binding_id:
                raise ValueError("decision binding_id must match artifact binding_id")
            if self.decision.market_as_of != self.artifact.market_as_of:
                raise ValueError(
                    "decision market_as_of must match artifact market_as_of"
                )
            if self.decision.asset != self.artifact.asset:
                raise ValueError("decision asset must match artifact asset")
            if self.decision.decision_timeframe != self.artifact.decision_timeframe:
                raise ValueError(
                    "decision timeframe must match artifact decision timeframe"
                )
            if self.decision.trigger_timeframe != self.artifact.trigger_timeframe:
                raise ValueError(
                    "decision trigger timeframe must match artifact trigger timeframe"
                )
        object.__setattr__(
            self,
            "metadata",
            _freeze_string_mapping(self.metadata, field_name="metadata"),
        )
        object.__setattr__(
            self,
            "proposed_next_state",
            freeze_model_state(self.proposed_next_state),
        )


def _normalize_context_mapping(
    value: Mapping[str, Any],
    *,
    field_name: str,
    freeze_values: bool = True,
) -> FrozenMapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    values = {
        key: deep_freeze(item) if freeze_values else item for key, item in value.items()
    }
    return FrozenMapping(values)


def _normalize_feature_mapping(
    value: Mapping[str, FeatureSnapshot], *, field_name: str
) -> FrozenMapping[str, FeatureSnapshot]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    normalized: dict[str, FeatureSnapshot] = {}
    for key, snapshot in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{field_name} keys must be strings")
        if not isinstance(snapshot, FeatureSnapshot):
            raise TypeError(f"{field_name} must contain FeatureSnapshot values")
        if key != snapshot.name:
            raise ValueError(f"{field_name} key must match FeatureSnapshot.name")
        normalized[key] = snapshot
    return FrozenMapping(dict(sorted(normalized.items())))


def _normalize_bar_views(
    value: Mapping[str, Sequence[CausalBarView] | CausalBarView],
) -> FrozenMapping[str, tuple[CausalBarView, ...]]:
    if not isinstance(value, Mapping):
        raise TypeError("causal_bar_views must be a mapping")
    normalized: dict[str, tuple[CausalBarView, ...]] = {}
    for timeframe, bars in value.items():
        _require_non_empty(timeframe, field_name="causal_bar_views timeframe")
        if isinstance(bars, CausalBarView):
            sequence = (bars,)
        elif isinstance(bars, Sequence) and not isinstance(bars, (str, bytes)):
            sequence = tuple(bars)
        else:
            raise TypeError("causal_bar_views values must be bar sequences")
        if any(not isinstance(bar, CausalBarView) for bar in sequence):
            raise TypeError("causal_bar_views must contain CausalBarView values")
        if any(bar.timeframe != timeframe for bar in sequence):
            raise ValueError("causal bar timeframe must match its mapping key")
        for previous, current in pairwise(sequence):
            if current.bar_open_at <= previous.bar_open_at:
                raise ValueError("causal bars must be chronologically ordered")
            if current.bar_open_at < previous.bar_close_at:
                raise ValueError("causal bars must not overlap")
            if current.bar_close_at <= previous.bar_close_at:
                raise ValueError("causal bars must be chronologically ordered")
            if current.market_as_of < previous.market_as_of:
                raise ValueError("causal bars must be chronologically ordered")
        normalized[timeframe] = sequence
    return FrozenMapping(normalized)


def _validate_causal_cutoff(
    bar_views: Mapping[str, Sequence[CausalBarView]], market_as_of: datetime
) -> None:
    for bars in bar_views.values():
        if any(bar.market_as_of > market_as_of for bar in bars):
            raise ValueError(
                "causal bar market_as_of cannot be after context market_as_of"
            )


def _validate_upstream_artifacts(
    artifacts: Mapping[str, ModelArtifact], context: ModelRequestContext
) -> None:
    for artifact in artifacts.values():
        if artifact.market_as_of != context.market_as_of:
            raise ValueError("upstream artifact market_as_of must match context")
        if artifact.lane_id != context.lane_id:
            raise ValueError("upstream artifact lane_id must match context")
        if artifact.asset != context.asset:
            raise ValueError("upstream artifact asset must match context")
        if artifact.decision_timeframe != context.decision_timeframe:
            raise ValueError("upstream artifact decision timeframe must match context")
        if artifact.trigger_timeframe != context.trigger_timeframe:
            raise ValueError("upstream artifact trigger timeframe must match context")


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelRequestContext:
    """Immutable pre-resolution context passed to ``data_requests``."""

    asset: str
    venue: str
    instrument_id: str
    lane_id: str
    binding_id: str
    market_as_of: datetime
    trigger_timeframe: str
    decision_timeframe: str
    trigger_mode: str
    decision_bar: CausalBarView | None
    decision_bar_closed: bool
    causal_bar_views: Mapping[str, Sequence[CausalBarView] | CausalBarView] = field(
        default_factory=dict
    )
    shared_features: Mapping[str, FeatureSnapshot] = field(default_factory=dict)
    upstream_artifacts: Mapping[str, ModelArtifact] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _normalize_context_identity(self)
        bar_views = _normalize_bar_views(self.causal_bar_views)
        _validate_causal_cutoff(bar_views, self.market_as_of)
        object.__setattr__(self, "causal_bar_views", bar_views)
        object.__setattr__(
            self,
            "shared_features",
            _normalize_feature_mapping(
                self.shared_features, field_name="shared_features"
            ),
        )
        artifacts = _normalize_context_mapping(
            self.upstream_artifacts,
            field_name="upstream_artifacts",
            freeze_values=False,
        )
        if any(not isinstance(value, ModelArtifact) for value in artifacts.values()):
            raise TypeError("upstream_artifacts must contain ModelArtifact values")
        object.__setattr__(self, "upstream_artifacts", artifacts)
        _validate_upstream_artifacts(artifacts, self)
        object.__setattr__(
            self,
            "provenance",
            _normalize_context_mapping(self.provenance, field_name="provenance"),
        )
        if self.decision_bar is not None:
            if not isinstance(self.decision_bar, CausalBarView):
                raise TypeError("decision_bar must be a CausalBarView or None")
            if self.decision_bar.market_as_of != self.market_as_of:
                raise ValueError(
                    "decision_bar market_as_of must match context market_as_of"
                )
            if self.decision_bar.timeframe != self.decision_timeframe:
                raise ValueError("decision_bar timeframe must match decision_timeframe")
            if self.decision_bar.closed != self.decision_bar_closed:
                raise ValueError("decision_bar_closed must match decision_bar.closed")


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionContext(ModelRequestContext):
    """Complete immutable model input after external data resolution."""

    external_data: Mapping[str, DataSnapshot] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ModelRequestContext.__post_init__(self)
        snapshots = _normalize_context_mapping(
            self.external_data,
            field_name="external_data",
            freeze_values=False,
        )
        if any(not isinstance(value, DataSnapshot) for value in snapshots.values()):
            raise TypeError("external_data must contain DataSnapshot values")
        for request_key, snapshot in snapshots.items():
            if request_key != snapshot.request_key:
                raise ValueError("external_data key must match snapshot request_key")
            if snapshot.event_time > self.market_as_of:
                raise ValueError(
                    "external snapshot event_time cannot be after context market_as_of"
                )
            if (
                snapshot.represented_end_at is not None
                and snapshot.represented_end_at > self.market_as_of
            ):
                raise ValueError(
                    "external snapshot window cannot extend past context market_as_of"
                )
        object.__setattr__(self, "external_data", snapshots)


def _normalize_context_identity(context: ModelRequestContext) -> None:
    for field_name in (
        "asset",
        "venue",
        "instrument_id",
        "lane_id",
        "binding_id",
        "trigger_timeframe",
        "decision_timeframe",
        "trigger_mode",
    ):
        _require_non_empty(getattr(context, field_name), field_name=field_name)
    require_utc(context.market_as_of, field_name="market_as_of")
    if not isinstance(context.decision_bar_closed, bool):
        raise TypeError("decision_bar_closed must be a bool")


@runtime_checkable
class DecisionModelPlugin(Protocol):
    """Minimal structural plugin contract with no infrastructure dependency."""

    spec: ModelSpec

    def data_requests(
        self,
        base_context: ModelRequestContext,
        state_snapshot: ModelState = None,
    ) -> Sequence[DataRequirement]: ...

    def evaluate(
        self,
        context: DecisionContext,
        state_snapshot: ModelState = None,
    ) -> ModelOutcome: ...


__all__ = [
    "Alignment",
    "CausalBarView",
    "DataMode",
    "DataRequest",
    "DataRequirement",
    "DataSnapshot",
    "DecisionContext",
    "DecisionModelPlugin",
    "DirectionHint",
    "FeatureRequirement",
    "FeatureSnapshot",
    "FrozenMapping",
    "ModelArtifact",
    "ModelDecision",
    "ModelDependencyRequirement",
    "ModelOutcome",
    "ModelOutputKind",
    "ModelRequestContext",
    "ModelSpec",
    "ModelState",
    "ResolvedCapability",
    "StateReconstructionRequirement",
    "WarmupRequirements",
    "deep_freeze",
    "freeze_model_state",
    "require_utc",
    "validate_data_snapshot",
]
