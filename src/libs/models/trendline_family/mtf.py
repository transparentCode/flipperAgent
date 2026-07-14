"""Causal, immutable, shadow-only multi-timeframe trendline composition.

This module projects already-confirmed single-timeframe snapshots.  It does
not create, refit, match, or mutate trendline families.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import math
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .config import (
    ResolvedTrendlineFamilyConfig,
    canonical_mtf_source_timeframes,
    canonical_timeframe_duration_seconds,
)
from .contracts import (
    ContractValidationError,
    FamilyLifecycleState,
    FamilyRole,
    LineGeometry,
    TrendlineFamilySnapshot,
    canonical_json,
    deterministic_hash,
    deterministic_id,
    parse_utc_isoformat,
    require_utc,
    trendline_family_snapshot_has_phase_g_evidence,
    validate_trendline_family_snapshot_identity,
)


_FLOAT_TOLERANCE = 1e-9


class MTFFreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE_INCLUDED = "STALE_INCLUDED"
    STALE_EXCLUDED = "STALE_EXCLUDED"
    MISSING = "MISSING"


class MTFRelationType(str, Enum):
    AGREEMENT = "AGREEMENT"
    CONFLUENCE = "CONFLUENCE"
    NESTED = "NESTED"
    DIVERGENCE = "DIVERGENCE"
    CONFLICT = "CONFLICT"
    INTERSECTION = "INTERSECTION"
    DISJOINT = "DISJOINT"


def timeframe_duration_seconds(timeframe: str) -> int:
    """Return a canonical fixed duration for Phase-H asynchronous diagnostics."""

    return canonical_timeframe_duration_seconds(timeframe)


def _timeframe_key(timeframe: str) -> tuple[int, str]:
    return (timeframe_duration_seconds(timeframe), timeframe)


def _text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _hash(value: Any, *, field_name: str) -> str:
    value = _text(value, field_name=field_name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ContractValidationError(f"{field_name} must be a lowercase SHA-256 hash")
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
    result = float(value)
    if not math.isfinite(result):
        raise ContractValidationError(f"{field_name} must be finite")
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise ContractValidationError(f"{field_name} must be at most {maximum}")
    return result


def _optional_number(
    value: Any,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    return None if value is None else _number(value, field_name=field_name, minimum=minimum, maximum=maximum)


def _integer(value: Any, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractValidationError(f"{field_name} must be an integer at least {minimum}")
    return value


def _optional_text(value: Any, *, field_name: str) -> str | None:
    return None if value is None else _text(value, field_name=field_name)


def _enum(value: Any, enum_type: type[Enum], *, field_name: str) -> Enum:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid {field_name}: {value!r}") from exc


def _freeze_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ContractValidationError(f"{field_name} must be a string-keyed mapping")
    return MappingProxyType({key: _freeze_value(item, field_name=f"{field_name}.{key}") for key, item in value.items()})


def _freeze_value(value: Any, *, field_name: str) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value, field_name=field_name)
    if isinstance(value, list) or isinstance(value, tuple):
        return tuple(_freeze_value(item, field_name=field_name) for item in value)
    if isinstance(value, set):
        raise ContractValidationError(f"{field_name} must not use unordered sets")
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractValidationError(f"{field_name} must not contain non-finite floats")
    return value


def _primitive(value: Any) -> Any:
    if isinstance(value, datetime):
        return require_utc(value).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, LineGeometry):
        return _primitive(value.to_dict())
    if isinstance(value, Mapping):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, tuple) or isinstance(value, list):
        return [_primitive(item) for item in value]
    return value


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=_FLOAT_TOLERANCE)


def _optional_close(left: float | None, right: float | None) -> bool:
    return (
        left is None and right is None
        or left is not None and right is not None and _close(left, right)
    )


def _projected_family_sort_key(item: "ProjectedMTFFamily") -> tuple[int, str, str]:
    return (*_timeframe_key(item.source_timeframe), item.source_family_id)


@dataclass(frozen=True)
class MTFNormalizationContext:
    """Caller-supplied decision-timeframe normalizer; the compositor fetches no data."""

    asset: str
    decision_timeframe: str
    atr: float
    decision_price: float | None = None
    policy: str = "decision_timeframe_atr"
    context_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", _text(self.asset, field_name="normalization asset"))
        timeframe_duration_seconds(self.decision_timeframe)
        object.__setattr__(self, "decision_timeframe", self.decision_timeframe)
        object.__setattr__(self, "atr", _number(self.atr, field_name="normalization atr", minimum=float.fromhex("0x1.0p-1022")))
        object.__setattr__(self, "decision_price", _optional_number(self.decision_price, field_name="decision_price"))
        object.__setattr__(self, "policy", _text(self.policy, field_name="normalization policy"))
        if self.policy != "decision_timeframe_atr":
            raise ContractValidationError("normalization policy must be decision_timeframe_atr")
        expected = deterministic_id(
            "mtf-normalization-context",
            {
                "asset": self.asset,
                "decision_timeframe": self.decision_timeframe,
                "atr": self.atr,
                "decision_price": self.decision_price,
                "policy": self.policy,
            },
        )
        if self.context_id is not None and self.context_id != expected:
            raise ContractValidationError("normalization context_id does not bind its payload")
        object.__setattr__(self, "context_id", expected)

    @property
    def timeframe_duration_seconds(self) -> int:
        return timeframe_duration_seconds(self.decision_timeframe)

    def to_dict(self) -> dict[str, Any]:
        return _primitive(
            {
                "asset": self.asset,
                "decision_timeframe": self.decision_timeframe,
                "atr": self.atr,
                "decision_price": self.decision_price,
                "policy": self.policy,
                "context_id": self.context_id,
            }
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MTFNormalizationContext":
        if not isinstance(value, Mapping):
            raise ContractValidationError("MTFNormalizationContext must be a mapping")
        try:
            return cls(
                asset=value["asset"],
                decision_timeframe=value["decision_timeframe"],
                atr=value["atr"],
                decision_price=value.get("decision_price"),
                policy=value.get("policy", "decision_timeframe_atr"),
                context_id=value.get("context_id"),
            )
        except ContractValidationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid MTFNormalizationContext payload") from exc


@dataclass(frozen=True)
class MTFPolicyAudit:
    """Frozen Phase-H policy needed to reproduce all composed evidence."""

    asset: str
    decision_timeframe: str
    model_version: str
    config_version: str
    mtf_config_hash: str
    source_timeframes: tuple[str, ...]
    minimum_confluence_timeframes: int
    max_source_age_bars: float
    stale_include_age_bars: float
    max_level_distance_atr: float
    max_corridor_separation_atr: float
    max_slope_delta_atr_per_hour: float
    intersection_horizon_bars: int
    normalization_policy: str

    def __post_init__(self) -> None:
        for name in (
            "asset",
            "decision_timeframe",
            "model_version",
            "config_version",
            "normalization_policy",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=f"MTF policy {name}"))
        timeframe_duration_seconds(self.decision_timeframe)
        object.__setattr__(self, "mtf_config_hash", _hash(self.mtf_config_hash, field_name="mtf_config_hash"))
        timeframes = tuple(self.source_timeframes)
        normalized_timeframes = canonical_mtf_source_timeframes(
            timeframes,
            field_name="MTF policy source_timeframes",
            require_nonempty=True,
        )
        if normalized_timeframes != timeframes:
            raise ContractValidationError("MTF policy source_timeframes require canonical unique ordering")
        object.__setattr__(self, "source_timeframes", timeframes)
        object.__setattr__(self, "minimum_confluence_timeframes", _integer(self.minimum_confluence_timeframes, field_name="minimum_confluence_timeframes", minimum=2))
        for name in (
            "max_source_age_bars",
            "stale_include_age_bars",
            "max_level_distance_atr",
            "max_corridor_separation_atr",
            "max_slope_delta_atr_per_hour",
        ):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=f"MTF policy {name}", minimum=0.0))
        if self.max_source_age_bars < self.stale_include_age_bars:
            raise ContractValidationError("MTF policy max source age cannot be below stale inclusion age")
        object.__setattr__(self, "intersection_horizon_bars", _integer(self.intersection_horizon_bars, field_name="intersection_horizon_bars", minimum=1))
        if self.normalization_policy != "decision_timeframe_atr":
            raise ContractValidationError("MTF policy normalization_policy must be decision_timeframe_atr")
        if self.mtf_config_hash != deterministic_hash(self.identity_payload()):
            raise ContractValidationError("mtf_config_hash must bind the complete MTF policy")

    def identity_payload(self) -> dict[str, Any]:
        """Match the dedicated Phase-H config identity, not tracker identity."""

        return {
            "asset": self.asset,
            "timeframe": self.decision_timeframe,
            "config_version": self.config_version,
            "mtf": {
                "enabled": True,
                "source_timeframes": self.source_timeframes,
                "minimum_confluence_timeframes": self.minimum_confluence_timeframes,
                "max_source_age_bars": self.max_source_age_bars,
                "stale_include_age_bars": self.stale_include_age_bars,
                "max_level_distance_atr": self.max_level_distance_atr,
                "max_corridor_separation_atr": self.max_corridor_separation_atr,
                "max_slope_delta_atr_per_hour": self.max_slope_delta_atr_per_hour,
                "intersection_horizon_bars": self.intersection_horizon_bars,
                "normalization_policy": self.normalization_policy,
            },
        }

    @classmethod
    def from_config(cls, *, config: ResolvedTrendlineFamilyConfig, decision_timeframe: str) -> "MTFPolicyAudit":
        mtf = config.mtf
        return cls(
            asset=config.asset,
            decision_timeframe=decision_timeframe,
            model_version=config.model_version,
            config_version=config.config_version,
            mtf_config_hash=config.mtf_config_hash,
            source_timeframes=mtf.source_timeframes,
            minimum_confluence_timeframes=mtf.minimum_confluence_timeframes,
            max_source_age_bars=mtf.max_source_age_bars,
            stale_include_age_bars=mtf.stale_include_age_bars,
            max_level_distance_atr=mtf.max_level_distance_atr,
            max_corridor_separation_atr=mtf.max_corridor_separation_atr,
            max_slope_delta_atr_per_hour=mtf.max_slope_delta_atr_per_hour,
            intersection_horizon_bars=mtf.intersection_horizon_bars,
            normalization_policy=mtf.normalization_policy,
        )

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self.__dict__)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MTFPolicyAudit":
        try:
            return cls(**{**value, "source_timeframes": tuple(value["source_timeframes"])})
        except ContractValidationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid MTFPolicyAudit payload") from exc


@dataclass(frozen=True)
class MTFSourceSnapshotReference:
    source_snapshot_id: str
    source_snapshot_timestamp: datetime
    source_timeframe: str
    asset: str
    model_version: str
    config_version: str
    resolved_config_hash: str
    source_normalization_atr: float | None
    source_age_seconds: float
    source_age_bars: float
    source_bar_duration_seconds: int
    freshness_state: MTFFreshnessState | str
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("source_snapshot_id", "source_timeframe", "asset", "model_version", "config_version"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        object.__setattr__(self, "source_snapshot_timestamp", require_utc(self.source_snapshot_timestamp))
        object.__setattr__(self, "resolved_config_hash", _hash(self.resolved_config_hash, field_name="source resolved_config_hash"))
        object.__setattr__(self, "source_normalization_atr", _optional_number(self.source_normalization_atr, field_name="source_normalization_atr", minimum=float.fromhex("0x1.0p-1022")))
        duration = timeframe_duration_seconds(self.source_timeframe)
        object.__setattr__(self, "source_bar_duration_seconds", _integer(self.source_bar_duration_seconds, field_name="source_bar_duration_seconds", minimum=1))
        if self.source_bar_duration_seconds != duration:
            raise ContractValidationError("source_bar_duration_seconds must match source_timeframe")
        object.__setattr__(self, "source_age_seconds", _number(self.source_age_seconds, field_name="source_age_seconds", minimum=0.0))
        object.__setattr__(self, "source_age_bars", _number(self.source_age_bars, field_name="source_age_bars", minimum=0.0))
        if not _close(self.source_age_bars, self.source_age_seconds / self.source_bar_duration_seconds):
            raise ContractValidationError("source_age_bars must match source age and timeframe duration")
        object.__setattr__(self, "freshness_state", _enum(self.freshness_state, MTFFreshnessState, field_name="freshness_state"))
        if self.freshness_state is MTFFreshnessState.MISSING:
            raise ContractValidationError("source snapshot references cannot use MISSING freshness")
        codes = tuple(self.reason_codes)
        if any(not isinstance(code, str) or not code for code in codes) or tuple(sorted(set(codes))) != codes:
            raise ContractValidationError("source reason_codes must be unique deterministic strings")
        object.__setattr__(self, "reason_codes", codes)

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self.__dict__)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MTFSourceSnapshotReference":
        try:
            return cls(
                source_snapshot_id=value["source_snapshot_id"], source_snapshot_timestamp=parse_utc_isoformat(value["source_snapshot_timestamp"]),
                source_timeframe=value["source_timeframe"], asset=value["asset"], model_version=value["model_version"],
                config_version=value["config_version"], resolved_config_hash=value["resolved_config_hash"], source_normalization_atr=value.get("source_normalization_atr"),
                source_age_seconds=value["source_age_seconds"], source_age_bars=value["source_age_bars"],
                source_bar_duration_seconds=value["source_bar_duration_seconds"], freshness_state=value["freshness_state"], reason_codes=tuple(value.get("reason_codes", ())),
            )
        except ContractValidationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid MTFSourceSnapshotReference payload") from exc


@dataclass(frozen=True)
class MTFSourceSnapshotAudit:
    """One canonical confirmed Phase-G source snapshot per included timeframe."""

    audit_id: str
    source_snapshot: TrendlineFamilySnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.source_snapshot, TrendlineFamilySnapshot):
            raise ContractValidationError(
                "MTF source snapshot audit requires TrendlineFamilySnapshot"
            )
        canonical = _canonical_confirmed_phase_g_source_snapshot(self.source_snapshot)
        object.__setattr__(self, "source_snapshot", canonical)
        object.__setattr__(self, "audit_id", _text(self.audit_id, field_name="source audit_id"))
        expected = deterministic_id(
            "mtf-source-snapshot-audit",
            {"source_snapshot": canonical.to_dict()},
        )
        if self.audit_id != expected:
            raise ContractValidationError("MTF source audit_id must bind canonical source snapshot")

    @classmethod
    def from_snapshot(cls, snapshot: TrendlineFamilySnapshot) -> "MTFSourceSnapshotAudit":
        canonical = _canonical_confirmed_phase_g_source_snapshot(snapshot)
        return cls(
            audit_id=deterministic_id(
                "mtf-source-snapshot-audit",
                {"source_snapshot": canonical.to_dict()},
            ),
            source_snapshot=canonical,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "source_snapshot": self.source_snapshot.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MTFSourceSnapshotAudit":
        try:
            return cls(
                audit_id=value["audit_id"],
                source_snapshot=TrendlineFamilySnapshot.from_dict(value["source_snapshot"]),
            )
        except ContractValidationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid MTFSourceSnapshotAudit payload") from exc


@dataclass(frozen=True)
class MTFSourceStatus:
    source_timeframe: str
    freshness_state: MTFFreshnessState | str
    reason_codes: tuple[str, ...]
    source_snapshot_id: str | None = None
    source_snapshot_timestamp: datetime | None = None
    source_age_seconds: float | None = None
    source_age_bars: float | None = None

    def __post_init__(self) -> None:
        timeframe_duration_seconds(self.source_timeframe)
        object.__setattr__(self, "source_timeframe", self.source_timeframe)
        object.__setattr__(self, "freshness_state", _enum(self.freshness_state, MTFFreshnessState, field_name="source freshness_state"))
        codes = tuple(self.reason_codes)
        if not codes or any(not isinstance(code, str) or not code for code in codes) or tuple(sorted(set(codes))) != codes:
            raise ContractValidationError("MTF source status requires deterministic reason_codes")
        object.__setattr__(self, "reason_codes", codes)
        object.__setattr__(self, "source_snapshot_id", _optional_text(self.source_snapshot_id, field_name="source_snapshot_id"))
        if self.source_snapshot_timestamp is not None:
            object.__setattr__(self, "source_snapshot_timestamp", require_utc(self.source_snapshot_timestamp))
        object.__setattr__(self, "source_age_seconds", _optional_number(self.source_age_seconds, field_name="source_age_seconds", minimum=0.0))
        object.__setattr__(self, "source_age_bars", _optional_number(self.source_age_bars, field_name="source_age_bars", minimum=0.0))
        missing = self.freshness_state is MTFFreshnessState.MISSING
        if missing != (self.source_snapshot_id is None):
            raise ContractValidationError("missing MTF source status must match source snapshot absence")
        if missing and any(value is not None for value in (self.source_snapshot_timestamp, self.source_age_seconds, self.source_age_bars)):
            raise ContractValidationError("missing MTF source cannot carry snapshot timing")
        if not missing and any(value is None for value in (self.source_snapshot_timestamp, self.source_age_seconds, self.source_age_bars)):
            raise ContractValidationError("present MTF source requires complete timing diagnostics")

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self.__dict__)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MTFSourceStatus":
        try:
            timestamp = value.get("source_snapshot_timestamp")
            return cls(
                source_timeframe=value["source_timeframe"], freshness_state=value["freshness_state"], reason_codes=tuple(value["reason_codes"]),
                source_snapshot_id=value.get("source_snapshot_id"), source_snapshot_timestamp=None if timestamp is None else parse_utc_isoformat(timestamp),
                source_age_seconds=value.get("source_age_seconds"), source_age_bars=value.get("source_age_bars"),
            )
        except ContractValidationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid MTFSourceStatus payload") from exc


@dataclass(frozen=True)
class ProjectedMTFMember:
    projected_member_id: str
    projected_family_id: str
    source_snapshot_id: str
    source_timeframe: str
    source_family_id: str
    source_member_id: str
    source_candidate_id: str
    source_geometry: LineGeometry
    source_geometry_hash: str
    projected_price: float
    projected_offset_from_representative: float
    source_order_index: int
    projection_timestamp: datetime

    def __post_init__(self) -> None:
        for name in (
            "projected_member_id", "projected_family_id", "source_snapshot_id", "source_timeframe", "source_family_id", "source_member_id", "source_candidate_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        timeframe_duration_seconds(self.source_timeframe)
        if not isinstance(self.source_geometry, LineGeometry):
            raise ContractValidationError("projected member source_geometry must use LineGeometry")
        object.__setattr__(self, "source_geometry_hash", _hash(self.source_geometry_hash, field_name="source_geometry_hash"))
        if self.source_geometry_hash != deterministic_hash(self.source_geometry.to_dict()):
            raise ContractValidationError("source_geometry_hash must bind source_geometry")
        object.__setattr__(self, "projected_price", _number(self.projected_price, field_name="projected_price"))
        object.__setattr__(self, "projected_offset_from_representative", _number(self.projected_offset_from_representative, field_name="projected_offset_from_representative"))
        object.__setattr__(self, "source_order_index", _integer(self.source_order_index, field_name="source_order_index"))
        object.__setattr__(self, "projection_timestamp", require_utc(self.projection_timestamp))
        expected = deterministic_id(
            "mtf-projected-member",
            {
                "projected_family_id": self.projected_family_id,
                "source_snapshot_id": self.source_snapshot_id,
                "source_timeframe": self.source_timeframe,
                "source_family_id": self.source_family_id,
                "source_member_id": self.source_member_id,
                "source_candidate_id": self.source_candidate_id,
                "source_geometry": self.source_geometry.to_dict(),
                "source_geometry_hash": self.source_geometry_hash,
                "projected_price": self.projected_price,
                "projected_offset_from_representative": self.projected_offset_from_representative,
                "source_order_index": self.source_order_index,
                "projection_timestamp": self.projection_timestamp,
            },
        )
        if self.projected_member_id != expected:
            raise ContractValidationError("projected_member_id does not bind projection provenance")

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self.__dict__)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProjectedMTFMember":
        try:
            return cls(
                **{
                    **value,
                    "source_geometry": LineGeometry.from_dict(value["source_geometry"]),
                    "projection_timestamp": parse_utc_isoformat(value["projection_timestamp"]),
                }
            )
        except ContractValidationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid ProjectedMTFMember payload") from exc


@dataclass(frozen=True)
class ProjectedMTFFamily:
    projected_family_id: str
    source_snapshot_id: str
    source_snapshot_timestamp: datetime
    source_timeframe: str
    source_family_id: str
    source_family_version: int
    source_family_role: FamilyRole | str
    source_family_lifecycle: FamilyLifecycleState | str
    source_representative_member_id: str
    source_ordered_member_ids: tuple[str, ...]
    ordered_source_member_ids: tuple[str, ...]
    projected_representative_price: float
    projected_representative_slope_per_second: float
    normalized_slope_atr_per_hour: float | None
    projected_corridor_lower_price: float
    projected_corridor_upper_price: float
    projected_corridor_width_atr: float
    source_confidence: float
    source_structural_importance: float
    source_event_id: str | None
    source_event_state: str | None
    source_age_seconds: float
    source_age_bars: float
    source_bar_duration_seconds: int
    freshness_state: MTFFreshnessState | str
    contributes_to_confluence: bool
    projected_order_changed: bool
    projection_timestamp: datetime
    model_version: str
    config_version: str
    resolved_config_hash: str

    def __post_init__(self) -> None:
        for name in (
            "projected_family_id", "source_snapshot_id", "source_timeframe", "source_family_id", "source_representative_member_id", "model_version", "config_version",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        object.__setattr__(self, "source_snapshot_timestamp", require_utc(self.source_snapshot_timestamp))
        object.__setattr__(self, "source_family_version", _integer(self.source_family_version, field_name="source_family_version", minimum=1))
        object.__setattr__(self, "source_family_role", _enum(self.source_family_role, FamilyRole, field_name="source_family_role"))
        object.__setattr__(self, "source_family_lifecycle", _enum(self.source_family_lifecycle, FamilyLifecycleState, field_name="source_family_lifecycle"))
        if self.source_family_role not in {FamilyRole.SUPPORT, FamilyRole.RESISTANCE}:
            raise ContractValidationError("projected family role must be SUPPORT or RESISTANCE")
        source_member_ids = tuple(self.source_ordered_member_ids)
        projected_member_ids = tuple(self.ordered_source_member_ids)
        if (
            not source_member_ids
            or any(not isinstance(item, str) or not item for item in source_member_ids)
            or len(set(source_member_ids)) != len(source_member_ids)
            or set(source_member_ids) != set(projected_member_ids)
            or len(set(projected_member_ids)) != len(projected_member_ids)
        ):
            raise ContractValidationError("source and projected member orders must contain identical unique IDs")
        object.__setattr__(self, "source_ordered_member_ids", source_member_ids)
        object.__setattr__(self, "ordered_source_member_ids", projected_member_ids)
        if self.source_representative_member_id not in source_member_ids:
            raise ContractValidationError("source representative member must be projected")
        for name in (
            "projected_representative_price", "projected_representative_slope_per_second", "projected_corridor_lower_price", "projected_corridor_upper_price",
        ):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=name))
        object.__setattr__(self, "normalized_slope_atr_per_hour", _optional_number(self.normalized_slope_atr_per_hour, field_name="normalized_slope_atr_per_hour"))
        object.__setattr__(self, "projected_corridor_width_atr", _number(self.projected_corridor_width_atr, field_name="projected_corridor_width_atr", minimum=0.0))
        if self.projected_corridor_lower_price > self.projected_corridor_upper_price:
            raise ContractValidationError("projected corridor lower price cannot exceed upper price")
        for name in ("source_confidence", "source_structural_importance"):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=name, minimum=0.0, maximum=1.0))
        object.__setattr__(self, "source_event_id", _optional_text(self.source_event_id, field_name="source_event_id"))
        object.__setattr__(self, "source_event_state", _optional_text(self.source_event_state, field_name="source_event_state"))
        object.__setattr__(self, "source_age_seconds", _number(self.source_age_seconds, field_name="source_age_seconds", minimum=0.0))
        object.__setattr__(self, "source_age_bars", _number(self.source_age_bars, field_name="source_age_bars", minimum=0.0))
        object.__setattr__(self, "source_bar_duration_seconds", _integer(self.source_bar_duration_seconds, field_name="source_bar_duration_seconds", minimum=1))
        if self.source_bar_duration_seconds != timeframe_duration_seconds(self.source_timeframe):
            raise ContractValidationError("projected source duration must match source timeframe")
        if not _close(self.source_age_bars, self.source_age_seconds / self.source_bar_duration_seconds):
            raise ContractValidationError("projected source age bars must match source timing")
        object.__setattr__(self, "freshness_state", _enum(self.freshness_state, MTFFreshnessState, field_name="projected freshness_state"))
        if not isinstance(self.contributes_to_confluence, bool) or not isinstance(self.projected_order_changed, bool):
            raise ContractValidationError("projected family booleans must be boolean")
        if self.contributes_to_confluence and self.freshness_state is MTFFreshnessState.STALE_EXCLUDED:
            raise ContractValidationError("stale-excluded projected families cannot contribute to confluence")
        object.__setattr__(self, "projection_timestamp", require_utc(self.projection_timestamp))
        object.__setattr__(self, "resolved_config_hash", _hash(self.resolved_config_hash, field_name="projected resolved_config_hash"))
        expected = deterministic_id("mtf-projected-family", self.identity_payload())
        if self.projected_family_id != expected:
            raise ContractValidationError("projected_family_id does not bind projection provenance")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "source_snapshot_id": self.source_snapshot_id,
            "source_snapshot_timestamp": self.source_snapshot_timestamp,
            "source_timeframe": self.source_timeframe,
            "source_family_id": self.source_family_id,
            "source_family_version": self.source_family_version,
            "source_family_role": self.source_family_role.value,
            "source_family_lifecycle": self.source_family_lifecycle.value,
            "source_representative_member_id": self.source_representative_member_id,
            "source_ordered_member_ids": self.source_ordered_member_ids,
            "ordered_source_member_ids": self.ordered_source_member_ids,
            "projected_representative_price": self.projected_representative_price,
            "projected_representative_slope_per_second": self.projected_representative_slope_per_second,
            "normalized_slope_atr_per_hour": self.normalized_slope_atr_per_hour,
            "projected_corridor_lower_price": self.projected_corridor_lower_price,
            "projected_corridor_upper_price": self.projected_corridor_upper_price,
            "projected_corridor_width_atr": self.projected_corridor_width_atr,
            "source_confidence": self.source_confidence,
            "source_structural_importance": self.source_structural_importance,
            "source_event_id": self.source_event_id,
            "source_event_state": self.source_event_state,
            "source_age_seconds": self.source_age_seconds,
            "source_age_bars": self.source_age_bars,
            "source_bar_duration_seconds": self.source_bar_duration_seconds,
            "freshness_state": self.freshness_state.value,
            "contributes_to_confluence": self.contributes_to_confluence,
            "projected_order_changed": self.projected_order_changed,
            "projection_timestamp": self.projection_timestamp,
            "model_version": self.model_version,
            "config_version": self.config_version,
            "resolved_config_hash": self.resolved_config_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self.__dict__)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProjectedMTFFamily":
        try:
            return cls(
                **{
                    **value,
                    "source_snapshot_timestamp": parse_utc_isoformat(value["source_snapshot_timestamp"]),
                    "projection_timestamp": parse_utc_isoformat(value["projection_timestamp"]),
                    "source_ordered_member_ids": tuple(value["source_ordered_member_ids"]),
                    "ordered_source_member_ids": tuple(value["ordered_source_member_ids"]),
                }
            )
        except ContractValidationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid ProjectedMTFFamily payload") from exc


@dataclass(frozen=True)
class MTFRelation:
    relation_id: str
    relation_type: MTFRelationType | str
    left_projected_family_id: str
    right_projected_family_id: str
    left_source_timeframe: str
    right_source_timeframe: str
    left_role: FamilyRole | str
    right_role: FamilyRole | str
    level_separation_atr: float | None
    corridor_overlap_ratio: float | None
    slope_disagreement_atr_per_hour: float | None
    conflict_severity: float | None
    intersection_timestamp: datetime | None
    intersection_seconds_from_decision: float | None
    intersection_price: float | None
    intersection_horizon_eligible: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("relation_id", "left_projected_family_id", "right_projected_family_id", "left_source_timeframe", "right_source_timeframe"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        if self.left_projected_family_id >= self.right_projected_family_id:
            raise ContractValidationError("MTF relation family IDs must use canonical ordering")
        timeframe_duration_seconds(self.left_source_timeframe)
        timeframe_duration_seconds(self.right_source_timeframe)
        object.__setattr__(self, "relation_type", _enum(self.relation_type, MTFRelationType, field_name="relation_type"))
        object.__setattr__(self, "left_role", _enum(self.left_role, FamilyRole, field_name="left_role"))
        object.__setattr__(self, "right_role", _enum(self.right_role, FamilyRole, field_name="right_role"))
        for name in ("level_separation_atr", "corridor_overlap_ratio", "slope_disagreement_atr_per_hour", "conflict_severity"):
            maximum = 1.0 if name in {"corridor_overlap_ratio", "conflict_severity"} else None
            object.__setattr__(self, name, _optional_number(getattr(self, name), field_name=name, minimum=0.0, maximum=maximum))
        if self.intersection_timestamp is not None:
            object.__setattr__(self, "intersection_timestamp", require_utc(self.intersection_timestamp))
        object.__setattr__(self, "intersection_seconds_from_decision", _optional_number(self.intersection_seconds_from_decision, field_name="intersection_seconds_from_decision", minimum=0.0))
        object.__setattr__(self, "intersection_price", _optional_number(self.intersection_price, field_name="intersection_price"))
        if not isinstance(self.intersection_horizon_eligible, bool):
            raise ContractValidationError("intersection_horizon_eligible must be boolean")
        intersection = (self.intersection_timestamp, self.intersection_seconds_from_decision, self.intersection_price)
        if any(value is None for value in intersection) and any(value is not None for value in intersection):
            raise ContractValidationError("intersection evidence must be complete or absent")
        if self.intersection_horizon_eligible != all(value is not None for value in intersection):
            raise ContractValidationError("intersection eligibility must match finite intersection evidence")
        codes = tuple(self.reason_codes)
        if not codes or tuple(sorted(set(codes))) != codes or any(not isinstance(code, str) or not code for code in codes):
            raise ContractValidationError("MTF relation reason_codes must be unique deterministic strings")
        object.__setattr__(self, "reason_codes", codes)
        expected = deterministic_id("mtf-relation", self.identity_payload())
        if self.relation_id != expected:
            raise ContractValidationError("relation_id does not bind relation evidence")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "relation_type": self.relation_type.value,
            "left_projected_family_id": self.left_projected_family_id,
            "right_projected_family_id": self.right_projected_family_id,
            "left_source_timeframe": self.left_source_timeframe,
            "right_source_timeframe": self.right_source_timeframe,
            "left_role": self.left_role.value,
            "right_role": self.right_role.value,
            "level_separation_atr": self.level_separation_atr,
            "corridor_overlap_ratio": self.corridor_overlap_ratio,
            "slope_disagreement_atr_per_hour": self.slope_disagreement_atr_per_hour,
            "conflict_severity": self.conflict_severity,
            "intersection_timestamp": self.intersection_timestamp,
            "intersection_seconds_from_decision": self.intersection_seconds_from_decision,
            "intersection_price": self.intersection_price,
            "intersection_horizon_eligible": self.intersection_horizon_eligible,
            "reason_codes": self.reason_codes,
        }

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self.__dict__)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MTFRelation":
        try:
            timestamp = value.get("intersection_timestamp")
            return cls(
                **{
                    **value,
                    "intersection_timestamp": None if timestamp is None else parse_utc_isoformat(timestamp),
                    "reason_codes": tuple(value["reason_codes"]),
                }
            )
        except ContractValidationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid MTFRelation payload") from exc


@dataclass(frozen=True)
class MTFCluster:
    cluster_id: str
    asset: str
    decision_timestamp: datetime
    role: FamilyRole | str
    projected_family_ids: tuple[str, ...]
    source_timeframes: tuple[str, ...]
    reference_projected_family_id: str
    timeframe_count: int
    family_count: int
    minimum_projected_price: float
    maximum_projected_price: float
    span_atr: float
    representative_level_dispersion_atr: float | None
    normalized_slope_dispersion: float | None
    corridor_overlap_ratio: float | None
    confluence_strength: float | None
    is_confluence: bool
    freshness_summary: str
    model_version: str
    config_version: str
    resolved_config_hash: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("cluster_id", "asset", "reference_projected_family_id", "freshness_summary", "model_version", "config_version"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        object.__setattr__(self, "decision_timestamp", require_utc(self.decision_timestamp))
        object.__setattr__(self, "role", _enum(self.role, FamilyRole, field_name="cluster role"))
        if self.role not in {FamilyRole.SUPPORT, FamilyRole.RESISTANCE}:
            raise ContractValidationError("MTF cluster role must be SUPPORT or RESISTANCE")
        ids = tuple(self.projected_family_ids)
        if not ids or tuple(sorted(set(ids))) != ids:
            raise ContractValidationError("cluster projected_family_ids must be unique and lexically ordered")
        object.__setattr__(self, "projected_family_ids", ids)
        timeframes = tuple(self.source_timeframes)
        if not timeframes or tuple(sorted(set(timeframes), key=_timeframe_key)) != timeframes:
            raise ContractValidationError("cluster source_timeframes must be unique canonical ordering")
        object.__setattr__(self, "source_timeframes", timeframes)
        if self.reference_projected_family_id not in ids:
            raise ContractValidationError("cluster reference must be a real projected family")
        object.__setattr__(self, "timeframe_count", _integer(self.timeframe_count, field_name="cluster timeframe_count", minimum=1))
        object.__setattr__(self, "family_count", _integer(self.family_count, field_name="cluster family_count", minimum=1))
        if self.family_count != len(ids) or self.timeframe_count != len(timeframes):
            raise ContractValidationError("cluster count fields must match membership")
        for name in ("minimum_projected_price", "maximum_projected_price"):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=name))
        if self.minimum_projected_price > self.maximum_projected_price:
            raise ContractValidationError("cluster price bounds are invalid")
        object.__setattr__(self, "span_atr", _number(self.span_atr, field_name="cluster span_atr", minimum=0.0))
        for name in ("representative_level_dispersion_atr", "normalized_slope_dispersion", "corridor_overlap_ratio", "confluence_strength"):
            maximum = 1.0 if name in {"corridor_overlap_ratio", "confluence_strength"} else None
            object.__setattr__(self, name, _optional_number(getattr(self, name), field_name=name, minimum=0.0, maximum=maximum))
        if not isinstance(self.is_confluence, bool):
            raise ContractValidationError("cluster is_confluence must be boolean")
        if self.is_confluence and self.timeframe_count < 2:
            raise ContractValidationError("singleton MTF cluster cannot claim confluence")
        if self.family_count == 1 and any(value is not None for value in (self.representative_level_dispersion_atr, self.normalized_slope_dispersion, self.corridor_overlap_ratio, self.confluence_strength)):
            raise ContractValidationError("singleton MTF cluster must leave pairwise statistics undefined")
        object.__setattr__(self, "resolved_config_hash", _hash(self.resolved_config_hash, field_name="cluster resolved_config_hash"))
        codes = tuple(self.reason_codes)
        if not codes or tuple(sorted(set(codes))) != codes or any(not isinstance(code, str) or not code for code in codes):
            raise ContractValidationError("cluster reason_codes must be unique deterministic strings")
        object.__setattr__(self, "reason_codes", codes)
        expected = deterministic_id("mtf-cluster", self.identity_payload())
        if self.cluster_id != expected:
            raise ContractValidationError("cluster_id does not bind cluster evidence")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset, "decision_timestamp": self.decision_timestamp, "role": self.role.value,
            "projected_family_ids": self.projected_family_ids, "source_timeframes": self.source_timeframes,
            "reference_projected_family_id": self.reference_projected_family_id, "timeframe_count": self.timeframe_count,
            "family_count": self.family_count, "minimum_projected_price": self.minimum_projected_price,
            "maximum_projected_price": self.maximum_projected_price, "span_atr": self.span_atr,
            "representative_level_dispersion_atr": self.representative_level_dispersion_atr,
            "normalized_slope_dispersion": self.normalized_slope_dispersion,
            "corridor_overlap_ratio": self.corridor_overlap_ratio, "confluence_strength": self.confluence_strength,
            "is_confluence": self.is_confluence, "freshness_summary": self.freshness_summary,
            "model_version": self.model_version, "config_version": self.config_version,
            "resolved_config_hash": self.resolved_config_hash, "reason_codes": self.reason_codes,
        }

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self.__dict__)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MTFCluster":
        try:
            return cls(
                **{
                    **value,
                    "decision_timestamp": parse_utc_isoformat(value["decision_timestamp"]),
                    "projected_family_ids": tuple(value["projected_family_ids"]),
                    "source_timeframes": tuple(value["source_timeframes"]),
                    "reason_codes": tuple(value["reason_codes"]),
                }
            )
        except ContractValidationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid MTFCluster payload") from exc


@dataclass(frozen=True)
class MTFGeometrySnapshot:
    mtf_snapshot_id: str
    asset: str
    decision_timestamp: datetime
    normalization_context: MTFNormalizationContext
    policy_audit: MTFPolicyAudit
    source_snapshot_audits: tuple[MTFSourceSnapshotAudit, ...]
    source_snapshots: tuple[MTFSourceSnapshotReference, ...]
    source_statuses: tuple[MTFSourceStatus, ...]
    projected_families: tuple[ProjectedMTFFamily, ...]
    projected_members: tuple[ProjectedMTFMember, ...]
    relations: tuple[MTFRelation, ...]
    clusters: tuple[MTFCluster, ...]
    model_version: str
    config_version: str
    resolved_config_hash: str
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("mtf_snapshot_id", "asset", "model_version", "config_version"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        object.__setattr__(self, "decision_timestamp", require_utc(self.decision_timestamp))
        if not isinstance(self.normalization_context, MTFNormalizationContext):
            raise ContractValidationError("MTF snapshot requires MTFNormalizationContext")
        if self.normalization_context.asset != self.asset:
            raise ContractValidationError("MTF normalization context asset mismatch")
        if not isinstance(self.policy_audit, MTFPolicyAudit):
            raise ContractValidationError("MTF snapshot requires MTFPolicyAudit")
        if (
            self.policy_audit.asset != self.asset
            or self.policy_audit.decision_timeframe != self.normalization_context.decision_timeframe
            or self.policy_audit.normalization_policy != self.normalization_context.policy
            or self.model_version != self.policy_audit.model_version
            or self.config_version != self.policy_audit.config_version
        ):
            raise ContractValidationError("MTF policy audit does not match composition context")
        source_audits = tuple(self.source_snapshot_audits)
        if (
            any(not isinstance(item, MTFSourceSnapshotAudit) for item in source_audits)
            or tuple(
                sorted(
                    source_audits,
                    key=lambda item: _timeframe_key(item.source_snapshot.timeframe),
                )
            )
            != source_audits
        ):
            raise ContractValidationError("MTF source snapshot audits require canonical ordering")
        if len({item.source_snapshot.timeframe for item in source_audits}) != len(source_audits):
            raise ContractValidationError("MTF snapshot cannot audit a timeframe more than once")
        _validate_policy_source_timeframes(
            (item.source_snapshot.timeframe for item in source_audits),
            policy=self.policy_audit,
        )
        if any(
            item.source_snapshot.asset != self.asset
            or item.source_snapshot.timestamp > self.decision_timestamp
            for item in source_audits
        ):
            raise ContractValidationError("MTF source audit provenance or causality is invalid")
        object.__setattr__(self, "source_snapshot_audits", source_audits)
        source_snapshots = tuple(self.source_snapshots)
        if any(not isinstance(item, MTFSourceSnapshotReference) for item in source_snapshots) or tuple(sorted(source_snapshots, key=lambda item: _timeframe_key(item.source_timeframe))) != source_snapshots:
            raise ContractValidationError("MTF source snapshots require canonical ordering")
        if len({item.source_timeframe for item in source_snapshots}) != len(source_snapshots):
            raise ContractValidationError("MTF snapshot cannot contain duplicate source timeframes")
        if any(item.asset != self.asset or item.source_snapshot_timestamp > self.decision_timestamp for item in source_snapshots):
            raise ContractValidationError("MTF source snapshot provenance or causality is invalid")
        object.__setattr__(self, "source_snapshots", source_snapshots)
        source_statuses = tuple(self.source_statuses)
        if any(not isinstance(item, MTFSourceStatus) for item in source_statuses) or tuple(sorted(source_statuses, key=lambda item: _timeframe_key(item.source_timeframe))) != source_statuses:
            raise ContractValidationError("MTF source statuses require canonical ordering")
        if len({item.source_timeframe for item in source_statuses}) != len(source_statuses):
            raise ContractValidationError("MTF source statuses cannot contain duplicate timeframes")
        by_timeframe = {item.source_timeframe: item for item in source_statuses}
        for source in source_snapshots:
            status = by_timeframe.get(source.source_timeframe)
            if status is None or status.source_snapshot_id != source.source_snapshot_id or status.freshness_state is not source.freshness_state:
                raise ContractValidationError("MTF source status must audit every source snapshot")
        object.__setattr__(self, "source_statuses", source_statuses)
        families = tuple(self.projected_families)
        if any(not isinstance(item, ProjectedMTFFamily) for item in families) or tuple(sorted(families, key=_projected_family_sort_key)) != families:
            raise ContractValidationError("projected MTF families require canonical ordering")
        if len({item.projected_family_id for item in families}) != len(families):
            raise ContractValidationError("projected MTF family IDs must be unique")
        source_refs = {item.source_snapshot_id: item for item in source_snapshots}
        for family in families:
            source = source_refs.get(family.source_snapshot_id)
            if source is None or source.source_timeframe != family.source_timeframe or family.projection_timestamp != self.decision_timestamp:
                raise ContractValidationError("projected MTF family source provenance is invalid")
            if family.model_version != source.model_version or family.config_version != source.config_version or family.resolved_config_hash != source.resolved_config_hash:
                raise ContractValidationError("projected family must preserve source model/config identity")
        object.__setattr__(self, "projected_families", families)
        members = tuple(self.projected_members)
        if any(not isinstance(item, ProjectedMTFMember) for item in members) or tuple(sorted(members, key=lambda item: (item.projected_family_id, item.source_order_index))) != members:
            raise ContractValidationError("projected MTF members require canonical family/order ordering")
        if len({item.projected_member_id for item in members}) != len(members):
            raise ContractValidationError("projected MTF member IDs must be unique")
        by_family = {item.projected_family_id: item for item in families}
        members_by_family: dict[str, list[ProjectedMTFMember]] = {}
        for member in members:
            family = by_family.get(member.projected_family_id)
            if family is None or member.source_snapshot_id != family.source_snapshot_id or member.source_timeframe != family.source_timeframe or member.source_family_id != family.source_family_id or member.projection_timestamp != self.decision_timestamp:
                raise ContractValidationError("projected MTF member source provenance is invalid")
            members_by_family.setdefault(member.projected_family_id, []).append(member)
        for family in families:
            grouped = members_by_family.get(family.projected_family_id, [])
            if tuple(item.source_member_id for item in grouped) != family.ordered_source_member_ids:
                raise ContractValidationError("projected family member ordering is invalid")
            if tuple(item.source_order_index for item in grouped) != tuple(range(len(grouped))):
                raise ContractValidationError("projected family member order indexes are invalid")
            prices = [item.projected_price for item in grouped]
            if not prices or not _close(min(prices), family.projected_corridor_lower_price) or not _close(max(prices), family.projected_corridor_upper_price):
                raise ContractValidationError("projected family corridor must derive from exact members")
        object.__setattr__(self, "projected_members", members)
        relations = tuple(self.relations)
        if any(not isinstance(item, MTFRelation) for item in relations) or tuple(sorted(relations, key=lambda item: item.relation_id)) != relations or len({item.relation_id for item in relations}) != len(relations):
            raise ContractValidationError("MTF relations require unique canonical ordering")
        for relation in relations:
            left, right = by_family.get(relation.left_projected_family_id), by_family.get(relation.right_projected_family_id)
            if left is None or right is None or relation.left_source_timeframe != left.source_timeframe or relation.right_source_timeframe != right.source_timeframe or relation.left_role is not left.source_family_role or relation.right_role is not right.source_family_role:
                raise ContractValidationError("MTF relation references invalid projected provenance")
        object.__setattr__(self, "relations", relations)
        clusters = tuple(self.clusters)
        if any(not isinstance(item, MTFCluster) for item in clusters) or tuple(sorted(clusters, key=lambda item: item.cluster_id)) != clusters or len({item.cluster_id for item in clusters}) != len(clusters):
            raise ContractValidationError("MTF clusters require unique canonical ordering")
        clustered_family_ids: set[str] = set()
        for cluster in clusters:
            cluster_families = [by_family.get(item) for item in cluster.projected_family_ids]
            if any(item is None for item in cluster_families) or any(item.source_family_role is not cluster.role for item in cluster_families):
                raise ContractValidationError("MTF cluster references invalid projected families")
            if (
                cluster.asset != self.asset
                or cluster.decision_timestamp != self.decision_timestamp
                or cluster.model_version != self.policy_audit.model_version
                or cluster.config_version != self.policy_audit.config_version
                or cluster.resolved_config_hash != self.policy_audit.mtf_config_hash
            ):
                raise ContractValidationError("MTF cluster model/config identity mismatch")
            if len({item.source_timeframe for item in cluster_families}) != len(cluster_families):
                raise ContractValidationError("MTF cluster may contain at most one family per timeframe")
            expected_timeframes = tuple(
                sorted({item.source_timeframe for item in cluster_families}, key=_timeframe_key)
            )
            prices = [item.projected_representative_price for item in cluster_families]
            if (
                cluster.source_timeframes != expected_timeframes
                or not _close(cluster.minimum_projected_price, min(prices))
                or not _close(cluster.maximum_projected_price, max(prices))
                or not _close(
                    cluster.span_atr,
                    (max(prices) - min(prices)) / self.normalization_context.atr,
                )
            ):
                raise ContractValidationError("MTF cluster statistics do not match projected families")
            if len(cluster_families) == 1:
                expected_overlap = expected_level_dispersion = expected_slope_dispersion = None
            else:
                expected_level_dispersion = (max(prices) - min(prices)) / self.normalization_context.atr
                slopes = [item.normalized_slope_atr_per_hour for item in cluster_families]
                expected_slope_dispersion = (
                    None if any(item is None for item in slopes) else max(slopes) - min(slopes)
                )
                expected_overlap = min(
                    _corridor_overlap(left, right)
                    for index, left in enumerate(cluster_families)
                    for right in cluster_families[index + 1 :]
                )
            if (
                not _optional_close(cluster.representative_level_dispersion_atr, expected_level_dispersion)
                or not _optional_close(cluster.normalized_slope_dispersion, expected_slope_dispersion)
                or not _optional_close(cluster.corridor_overlap_ratio, expected_overlap)
            ):
                raise ContractValidationError("MTF cluster pairwise metrics do not match projected families")
            expected_freshness = {item.freshness_state for item in cluster_families}
            expected_summary = (
                next(iter(expected_freshness)).value
                if len(expected_freshness) == 1
                else "MIXED"
            )
            if cluster.freshness_summary != expected_summary:
                raise ContractValidationError("MTF cluster freshness summary does not match projected families")
            if clustered_family_ids & set(cluster.projected_family_ids):
                raise ContractValidationError("projected family cannot belong to multiple MTF clusters")
            clustered_family_ids.update(cluster.projected_family_ids)
        object.__setattr__(self, "clusters", clusters)
        object.__setattr__(self, "resolved_config_hash", _hash(self.resolved_config_hash, field_name="MTF resolved_config_hash"))
        if self.resolved_config_hash != self.policy_audit.mtf_config_hash:
            raise ContractValidationError("MTF snapshot config hash must equal MTF policy hash")
        object.__setattr__(self, "diagnostics", _freeze_mapping(self.diagnostics, field_name="MTF diagnostics"))
        _validate_mtf_snapshot_semantics(self)
        expected = compute_mtf_snapshot_id(self)
        if self.mtf_snapshot_id != expected:
            raise ContractValidationError("mtf_snapshot_id must bind complete MTF evidence")

    def identity_payload(self) -> dict[str, Any]:
        return _mtf_snapshot_identity_payload(
            asset=self.asset,
            decision_timestamp=self.decision_timestamp,
            normalization_context=self.normalization_context,
            policy_audit=self.policy_audit,
            source_snapshot_audits=self.source_snapshot_audits,
            source_snapshots=self.source_snapshots,
            source_statuses=self.source_statuses,
            projected_families=self.projected_families,
            projected_members=self.projected_members,
            relations=self.relations,
            clusters=self.clusters,
            model_version=self.model_version,
            config_version=self.config_version,
            resolved_config_hash=self.resolved_config_hash,
            diagnostics=self.diagnostics,
        )

    def to_dict(self) -> dict[str, Any]:
        return _primitive({"mtf_snapshot_id": self.mtf_snapshot_id, **self.identity_payload()})

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MTFGeometrySnapshot":
        try:
            return cls(
                mtf_snapshot_id=value["mtf_snapshot_id"], asset=value["asset"], decision_timestamp=parse_utc_isoformat(value["decision_timestamp"]),
                normalization_context=MTFNormalizationContext.from_dict(value["normalization_context"]),
                policy_audit=MTFPolicyAudit.from_dict(value["policy_audit"]),
                source_snapshot_audits=tuple(
                    MTFSourceSnapshotAudit.from_dict(item)
                    for item in value["source_snapshot_audits"]
                ),
                source_snapshots=tuple(MTFSourceSnapshotReference.from_dict(item) for item in value["source_snapshots"]),
                source_statuses=tuple(MTFSourceStatus.from_dict(item) for item in value["source_statuses"]),
                projected_families=tuple(ProjectedMTFFamily.from_dict(item) for item in value["projected_families"]),
                projected_members=tuple(ProjectedMTFMember.from_dict(item) for item in value["projected_members"]),
                relations=tuple(MTFRelation.from_dict(item) for item in value["relations"]),
                clusters=tuple(MTFCluster.from_dict(item) for item in value["clusters"]),
                model_version=value["model_version"], config_version=value["config_version"], resolved_config_hash=value["resolved_config_hash"], diagnostics=value.get("diagnostics", {}),
            )
        except ContractValidationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid MTFGeometrySnapshot payload") from exc


def compute_mtf_snapshot_id(snapshot: MTFGeometrySnapshot) -> str:
    """Compute the content-addressed ID without accepting caller-controlled state."""

    return deterministic_id("mtf-geometry-snapshot", snapshot.identity_payload())


def _mtf_snapshot_identity_payload(
    *,
    asset: str,
    decision_timestamp: datetime,
    normalization_context: MTFNormalizationContext,
    policy_audit: MTFPolicyAudit,
    source_snapshot_audits: tuple[MTFSourceSnapshotAudit, ...],
    source_snapshots: tuple[MTFSourceSnapshotReference, ...],
    source_statuses: tuple[MTFSourceStatus, ...],
    projected_families: tuple[ProjectedMTFFamily, ...],
    projected_members: tuple[ProjectedMTFMember, ...],
    relations: tuple[MTFRelation, ...],
    clusters: tuple[MTFCluster, ...],
    model_version: str,
    config_version: str,
    resolved_config_hash: str,
    diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "asset": asset,
        "decision_timestamp": decision_timestamp,
        "normalization_context": normalization_context.to_dict(),
        "policy_audit": policy_audit.to_dict(),
        "source_snapshot_audits": tuple(item.to_dict() for item in source_snapshot_audits),
        "source_snapshots": tuple(item.to_dict() for item in source_snapshots),
        "source_statuses": tuple(item.to_dict() for item in source_statuses),
        "projected_families": tuple(item.to_dict() for item in projected_families),
        "projected_members": tuple(item.to_dict() for item in projected_members),
        "relations": tuple(item.to_dict() for item in relations),
        "clusters": tuple(item.to_dict() for item in clusters),
        "model_version": model_version,
        "config_version": config_version,
        "resolved_config_hash": resolved_config_hash,
        "diagnostics": diagnostics,
    }


def _validate_mtf_snapshot_semantics(snapshot: MTFGeometrySnapshot) -> None:
    """Rebuild all derived Phase-H evidence from persisted source audits and policy."""

    policy = snapshot.policy_audit
    expected_references, expected_statuses = _source_audit(
        source_snapshot_audits=snapshot.source_snapshot_audits,
        decision_timestamp=snapshot.decision_timestamp,
        policy=policy,
    )
    if snapshot.source_snapshots != expected_references:
        raise ContractValidationError("MTF source references do not match canonical source audits")
    if snapshot.source_statuses != expected_statuses:
        raise ContractValidationError("MTF source statuses do not match canonical source audits")
    expected_families, expected_members, representative_geometries = _project_families(
        source_snapshot_audits=snapshot.source_snapshot_audits,
        source_references=expected_references,
        decision_timestamp=snapshot.decision_timestamp,
        normalization_context=snapshot.normalization_context,
    )
    if snapshot.projected_families != expected_families:
        raise ContractValidationError("projected MTF families do not match canonical source audits")
    if snapshot.projected_members != expected_members:
        raise ContractValidationError("projected MTF members do not match canonical source audits")
    expected_relations = _build_relations(
        families=expected_families,
        geometries=representative_geometries,
        decision_timestamp=snapshot.decision_timestamp,
        normalization_context=snapshot.normalization_context,
        policy=policy,
    )
    if snapshot.relations != expected_relations:
        raise ContractValidationError("MTF relations do not match projected evidence and policy")
    expected_clusters = _build_clusters(
        families=expected_families,
        relations=expected_relations,
        decision_timestamp=snapshot.decision_timestamp,
        normalization_context=snapshot.normalization_context,
        policy=policy,
        asset=policy.asset,
        model_version=policy.model_version,
        config_version=policy.config_version,
        mtf_config_hash=policy.mtf_config_hash,
    )
    if snapshot.clusters != expected_clusters:
        raise ContractValidationError("MTF clusters do not match complete-linkage policy evidence")
    expected_diagnostics = _mtf_diagnostics(
        policy=policy,
        source_statuses=expected_statuses,
        projected_families=expected_families,
        projected_members=expected_members,
        relations=expected_relations,
        clusters=expected_clusters,
    )
    if dict(snapshot.diagnostics) != expected_diagnostics:
        raise ContractValidationError("MTF diagnostics do not match persisted typed evidence")


def _mtf_diagnostics(
    *,
    policy: MTFPolicyAudit,
    source_statuses: tuple[MTFSourceStatus, ...],
    projected_families: tuple[ProjectedMTFFamily, ...],
    projected_members: tuple[ProjectedMTFMember, ...],
    relations: tuple[MTFRelation, ...],
    clusters: tuple[MTFCluster, ...],
) -> dict[str, Any]:
    return {
        "mtf_enabled": True,
        "normalization_policy": policy.normalization_policy,
        "mtf_config_hash": policy.mtf_config_hash,
        "configured_source_timeframes": policy.source_timeframes,
        "source_timeframe_count": sum(status.freshness_state is not MTFFreshnessState.MISSING for status in source_statuses),
        "missing_source_timeframes": tuple(status.source_timeframe for status in source_statuses if status.freshness_state is MTFFreshnessState.MISSING),
        "stale_excluded_source_timeframes": tuple(status.source_timeframe for status in source_statuses if status.freshness_state is MTFFreshnessState.STALE_EXCLUDED),
        "projected_family_count": len(projected_families),
        "projected_member_count": len(projected_members),
        "relation_count": len(relations),
        "cluster_count": len(clusters),
    }


def serialize_mtf_snapshot(snapshot: MTFGeometrySnapshot) -> str:
    if not isinstance(snapshot, MTFGeometrySnapshot):
        raise ContractValidationError("MTF snapshot serialization requires MTFGeometrySnapshot")
    return canonical_json(snapshot.to_dict())


def deserialize_mtf_snapshot(payload: str) -> MTFGeometrySnapshot:
    if not isinstance(payload, str):
        raise ContractValidationError("MTF snapshot payload must be JSON text")
    try:
        return MTFGeometrySnapshot.from_dict(json.loads(payload))
    except ContractValidationError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractValidationError("invalid MTF snapshot JSON payload") from exc


def compose_mtf_snapshot(
    *,
    source_snapshots: Mapping[str, TrendlineFamilySnapshot],
    decision_timestamp: datetime,
    normalization_context: MTFNormalizationContext,
    config: ResolvedTrendlineFamilyConfig,
) -> MTFGeometrySnapshot:
    """Compose immutable Phase-G sources at one causal decision timestamp."""

    if not isinstance(config, ResolvedTrendlineFamilyConfig):
        raise ContractValidationError("MTF composition requires ResolvedTrendlineFamilyConfig")
    if not config.mtf.enabled:
        raise ContractValidationError("MTF composition requires mtf.enabled=True")
    if not isinstance(source_snapshots, Mapping):
        raise ContractValidationError("source_snapshots must be a timeframe mapping")
    if normalization_context.policy != config.mtf.normalization_policy:
        raise ContractValidationError("normalization context policy must match resolved MTF config")
    if normalization_context.asset != config.asset:
        raise ContractValidationError("normalization context asset must match resolved config")
    if normalization_context.decision_timeframe != config.timeframe:
        raise ContractValidationError("normalization context timeframe must match resolved config")
    decision_timestamp = require_utc(decision_timestamp, field_name="MTF decision_timestamp")
    policy_audit = MTFPolicyAudit.from_config(
        config=config,
        decision_timeframe=normalization_context.decision_timeframe,
    )
    normalized_sources = _validate_sources(
        source_snapshots=source_snapshots,
        decision_timestamp=decision_timestamp,
        policy=policy_audit,
    )
    source_snapshot_audits = tuple(
        MTFSourceSnapshotAudit.from_snapshot(snapshot)
        for _, snapshot in normalized_sources
    )
    source_references, source_statuses = _source_audit(
        source_snapshot_audits=source_snapshot_audits,
        decision_timestamp=decision_timestamp,
        policy=policy_audit,
    )
    projected_families, projected_members, representative_geometries = _project_families(
        source_snapshot_audits=source_snapshot_audits,
        source_references=source_references,
        decision_timestamp=decision_timestamp,
        normalization_context=normalization_context,
    )
    relations = _build_relations(
        families=projected_families,
        geometries=representative_geometries,
        decision_timestamp=decision_timestamp,
        normalization_context=normalization_context,
        policy=policy_audit,
    )
    clusters = _build_clusters(
        families=projected_families,
        relations=relations,
        decision_timestamp=decision_timestamp,
        normalization_context=normalization_context,
        policy=policy_audit,
        asset=config.asset,
        model_version=config.model_version,
        config_version=config.config_version,
        mtf_config_hash=config.mtf_config_hash,
    )
    diagnostics = _mtf_diagnostics(
        policy=policy_audit,
        source_statuses=source_statuses,
        projected_families=projected_families,
        projected_members=projected_members,
        relations=relations,
        clusters=clusters,
    )
    snapshot_id = deterministic_id(
        "mtf-geometry-snapshot",
        _mtf_snapshot_identity_payload(
            asset=config.asset,
            decision_timestamp=decision_timestamp,
            normalization_context=normalization_context,
            policy_audit=policy_audit,
            source_snapshot_audits=source_snapshot_audits,
            source_snapshots=source_references,
            source_statuses=source_statuses,
            projected_families=projected_families,
            projected_members=projected_members,
            relations=relations,
            clusters=clusters,
            model_version=config.model_version,
            config_version=config.config_version,
            resolved_config_hash=config.mtf_config_hash,
            diagnostics=diagnostics,
        ),
    )
    return MTFGeometrySnapshot(
        mtf_snapshot_id=snapshot_id,
        asset=config.asset,
        decision_timestamp=decision_timestamp,
        normalization_context=normalization_context,
        policy_audit=policy_audit,
        source_snapshot_audits=source_snapshot_audits,
        source_snapshots=source_references,
        source_statuses=source_statuses,
        projected_families=projected_families,
        projected_members=projected_members,
        relations=relations,
        clusters=clusters,
        model_version=config.model_version,
        config_version=config.config_version,
        resolved_config_hash=config.mtf_config_hash,
        diagnostics=diagnostics,
    )


def _validate_sources(
    *,
    source_snapshots: Mapping[str, TrendlineFamilySnapshot],
    decision_timestamp: datetime,
    policy: MTFPolicyAudit,
) -> tuple[tuple[str, TrendlineFamilySnapshot], ...]:
    pairs: list[tuple[str, TrendlineFamilySnapshot]] = []
    seen_timeframes: set[str] = set()
    for key, snapshot in source_snapshots.items():
        if not isinstance(key, str):
            raise ContractValidationError("source snapshot mapping keys must be timeframes")
        timeframe_duration_seconds(key)
        if not isinstance(snapshot, TrendlineFamilySnapshot):
            raise ContractValidationError("source snapshots must use TrendlineFamilySnapshot")
        if snapshot.timeframe != key:
            raise ContractValidationError("source snapshot mapping key must match snapshot timeframe")
        if key in seen_timeframes:
            raise ContractValidationError("duplicate source timeframe")
        seen_timeframes.add(key)
        if snapshot.asset != policy.asset:
            raise ContractValidationError("source snapshot asset mismatch")
        if snapshot.timestamp > decision_timestamp:
            raise ContractValidationError("future source snapshot cannot enter MTF composition")
        _validate_confirmed_phase_g_source(snapshot)
        pairs.append((key, snapshot))
    _validate_policy_source_timeframes(seen_timeframes, policy=policy)
    return tuple(sorted(pairs, key=lambda item: _timeframe_key(item[0])))


def _validate_policy_source_timeframes(
    timeframes: Iterable[str],
    *,
    policy: MTFPolicyAudit,
) -> None:
    """Enforce one source-timeframe allowlist for runtime and persisted MTF."""

    unexpected = set(timeframes) - set(policy.source_timeframes)
    if unexpected:
        raise ContractValidationError(
            f"source timeframe is not configured for MTF: {sorted(unexpected)}"
        )


def _validate_confirmed_phase_g_source(snapshot: TrendlineFamilySnapshot) -> None:
    if not trendline_family_snapshot_has_phase_g_evidence(snapshot):
        raise ContractValidationError("MTF composition requires a canonical Phase-G source snapshot")
    validate_trendline_family_snapshot_identity(snapshot)
    diagnostics = snapshot.diagnostics
    if (
        diagnostics.get("incomplete_bar") is True
        or diagnostics.get("is_incomplete") is True
        or diagnostics.get("confirmed_bar") is False
    ):
        raise ContractValidationError("incomplete source snapshot cannot enter MTF composition")


def _canonical_confirmed_phase_g_source_snapshot(
    snapshot: TrendlineFamilySnapshot,
) -> TrendlineFamilySnapshot:
    """Round-trip source payload before MTF stores or derives from it."""

    if not isinstance(snapshot, TrendlineFamilySnapshot):
        raise ContractValidationError("MTF source audit requires TrendlineFamilySnapshot")
    canonical = TrendlineFamilySnapshot.from_dict(snapshot.to_dict())
    _validate_confirmed_phase_g_source(canonical)
    return canonical


def _freshness(*, age_bars: float, policy: MTFPolicyAudit) -> tuple[MTFFreshnessState, tuple[str, ...]]:
    if age_bars <= policy.stale_include_age_bars:
        return MTFFreshnessState.FRESH, ("fresh",)
    if age_bars <= policy.max_source_age_bars:
        return MTFFreshnessState.STALE_INCLUDED, ("stale_included",)
    return MTFFreshnessState.STALE_EXCLUDED, ("stale_excluded_hard_max",)


def _source_audit(
    *,
    source_snapshot_audits: tuple[MTFSourceSnapshotAudit, ...],
    decision_timestamp: datetime,
    policy: MTFPolicyAudit,
) -> tuple[tuple[MTFSourceSnapshotReference, ...], tuple[MTFSourceStatus, ...]]:
    references: list[MTFSourceSnapshotReference] = []
    statuses: list[MTFSourceStatus] = []
    _validate_policy_source_timeframes(
        (audit.source_snapshot.timeframe for audit in source_snapshot_audits),
        policy=policy,
    )
    for audit in source_snapshot_audits:
        snapshot = audit.source_snapshot
        timeframe = snapshot.timeframe
        duration = timeframe_duration_seconds(timeframe)
        age_seconds = (decision_timestamp - snapshot.timestamp).total_seconds()
        age_bars = age_seconds / duration
        state, codes = _freshness(age_bars=age_bars, policy=policy)
        reference = MTFSourceSnapshotReference(
            source_snapshot_id=snapshot.snapshot_id,
            source_snapshot_timestamp=snapshot.timestamp,
            source_timeframe=timeframe,
            asset=snapshot.asset,
            model_version=snapshot.model_version,
            config_version=snapshot.config_version,
            resolved_config_hash=snapshot.resolved_config_hash,
            source_normalization_atr=_source_atr(snapshot),
            source_age_seconds=age_seconds,
            source_age_bars=age_bars,
            source_bar_duration_seconds=duration,
            freshness_state=state,
            reason_codes=codes,
        )
        references.append(reference)
        statuses.append(
            MTFSourceStatus(
                source_timeframe=timeframe,
                freshness_state=state,
                reason_codes=codes,
                source_snapshot_id=snapshot.snapshot_id,
                source_snapshot_timestamp=snapshot.timestamp,
                source_age_seconds=age_seconds,
                source_age_bars=age_bars,
            )
        )
    actual = {audit.source_snapshot.timeframe for audit in source_snapshot_audits}
    for timeframe in policy.source_timeframes:
        if timeframe not in actual:
            statuses.append(
                MTFSourceStatus(
                    source_timeframe=timeframe,
                    freshness_state=MTFFreshnessState.MISSING,
                    reason_codes=("missing_source_snapshot",),
                )
            )
    return (
        tuple(sorted(references, key=lambda item: _timeframe_key(item.source_timeframe))),
        tuple(sorted(statuses, key=lambda item: _timeframe_key(item.source_timeframe))),
    )


def _source_atr(snapshot: TrendlineFamilySnapshot) -> float | None:
    value = snapshot.diagnostics.get("normalization_atr")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0.0:
        return None
    return float(value)


def _project_families(
    *,
    source_snapshot_audits: tuple[MTFSourceSnapshotAudit, ...],
    source_references: tuple[MTFSourceSnapshotReference, ...],
    decision_timestamp: datetime,
    normalization_context: MTFNormalizationContext,
) -> tuple[tuple[ProjectedMTFFamily, ...], tuple[ProjectedMTFMember, ...], Mapping[str, LineGeometry]]:
    reference_by_timeframe = {reference.source_timeframe: reference for reference in source_references}
    families: list[ProjectedMTFFamily] = []
    members: list[ProjectedMTFMember] = []
    geometries: dict[str, LineGeometry] = {}
    for audit in source_snapshot_audits:
        snapshot = audit.source_snapshot
        timeframe = snapshot.timeframe
        reference = reference_by_timeframe[timeframe]
        source_atr = reference.source_normalization_atr
        event_by_family = {event.family_id: event for event in snapshot.interaction_events}
        corridor_by_family = {corridor.family_id: corridor for corridor in snapshot.corridors}
        for family in sorted(snapshot.active_families + snapshot.dormant_families, key=lambda item: item.family_id):
            representative = next(member for member in family.members if member.member_id == family.representative_member_id)
            projected_unsorted = [
                (member, member.geometry.value_at(decision_timestamp))
                for member in family.members
            ]
            projected_unsorted.sort(key=lambda item: (item[1], item[0].member_id))
            projected_member_ids = tuple(item.member_id for item, _ in projected_unsorted)
            corridor = corridor_by_family.get(family.family_id)
            if corridor is None:
                raise ContractValidationError("Phase-G source family is missing its corridor audit")
            source_member_ids = corridor.ordered_member_ids
            order_changed = projected_member_ids != source_member_ids
            representative_price = representative.geometry.value_at(decision_timestamp)
            lower_price = projected_unsorted[0][1]
            upper_price = projected_unsorted[-1][1]
            event = event_by_family.get(family.family_id)
            normalized_slope = None if source_atr is None else representative.geometry.slope_per_second * 3600.0 / source_atr
            contributes = reference.freshness_state is not MTFFreshnessState.STALE_EXCLUDED and source_atr is not None
            family_payload = _projected_family_payload(
                snapshot=snapshot,
                family=family,
                reference=reference,
                source_atr=source_atr,
                decision_timestamp=decision_timestamp,
                normalization_context=normalization_context,
                source_member_ids=source_member_ids,
                projected_member_ids=projected_member_ids,
                projected_order_changed=order_changed,
            )
            family_id = deterministic_id("mtf-projected-family", family_payload)
            projected_family = ProjectedMTFFamily(
                projected_family_id=family_id,
                source_snapshot_id=snapshot.snapshot_id,
                source_snapshot_timestamp=snapshot.timestamp,
                source_timeframe=timeframe,
                source_family_id=family.family_id,
                source_family_version=family.version,
                source_family_role=family.current_role,
                source_family_lifecycle=family.lifecycle_state,
                source_representative_member_id=family.representative_member_id,
                source_ordered_member_ids=source_member_ids,
                ordered_source_member_ids=projected_member_ids,
                projected_representative_price=representative_price,
                projected_representative_slope_per_second=representative.geometry.slope_per_second,
                normalized_slope_atr_per_hour=normalized_slope,
                projected_corridor_lower_price=lower_price,
                projected_corridor_upper_price=upper_price,
                projected_corridor_width_atr=(upper_price - lower_price) / normalization_context.atr,
                source_confidence=family.confidence,
                source_structural_importance=family.structural_importance,
                source_event_id=None if event is None else event.event_id,
                source_event_state=None if event is None else event.state.value,
                source_age_seconds=reference.source_age_seconds,
                source_age_bars=reference.source_age_bars,
                source_bar_duration_seconds=reference.source_bar_duration_seconds,
                freshness_state=reference.freshness_state,
                contributes_to_confluence=contributes,
                projected_order_changed=order_changed,
                projection_timestamp=decision_timestamp,
                model_version=snapshot.model_version,
                config_version=snapshot.config_version,
                resolved_config_hash=snapshot.resolved_config_hash,
            )
            families.append(projected_family)
            geometries[family_id] = representative.geometry
            for order_index, (member, projected_price) in enumerate(projected_unsorted):
                member_payload = {
                    "projected_family_id": family_id,
                    "source_snapshot_id": snapshot.snapshot_id,
                    "source_timeframe": timeframe,
                    "source_family_id": family.family_id,
                    "source_member_id": member.member_id,
                    "source_candidate_id": member.candidate_id,
                    "source_geometry": member.geometry,
                    "source_geometry_hash": deterministic_hash(member.geometry.to_dict()),
                    "projected_price": projected_price,
                    "projected_offset_from_representative": projected_price - representative_price,
                    "source_order_index": order_index,
                    "projection_timestamp": decision_timestamp,
                }
                member_identity_payload = {
                    **member_payload,
                    "source_geometry": member.geometry.to_dict(),
                }
                members.append(
                    ProjectedMTFMember(
                        projected_member_id=deterministic_id(
                            "mtf-projected-member", member_identity_payload
                        ),
                        **member_payload,
                    )
                )
    return (
        tuple(sorted(families, key=_projected_family_sort_key)),
        tuple(sorted(members, key=lambda item: (item.projected_family_id, item.source_order_index))),
        MappingProxyType(geometries),
    )


def _projected_family_payload(
    *,
    snapshot: TrendlineFamilySnapshot,
    family: Any,
    reference: MTFSourceSnapshotReference,
    source_atr: float | None,
    decision_timestamp: datetime,
    normalization_context: MTFNormalizationContext,
    source_member_ids: tuple[str, ...],
    projected_member_ids: tuple[str, ...],
    projected_order_changed: bool,
) -> dict[str, Any]:
    representative = next(member for member in family.members if member.member_id == family.representative_member_id)
    prices = [member.geometry.value_at(decision_timestamp) for member in family.members]
    event = next((event for event in snapshot.interaction_events if event.family_id == family.family_id), None)
    return {
        "source_snapshot_id": snapshot.snapshot_id,
        "source_snapshot_timestamp": snapshot.timestamp,
        "source_timeframe": snapshot.timeframe,
        "source_family_id": family.family_id,
        "source_family_version": family.version,
        "source_family_role": family.current_role.value,
        "source_family_lifecycle": family.lifecycle_state.value,
        "source_representative_member_id": family.representative_member_id,
        "source_ordered_member_ids": source_member_ids,
        "ordered_source_member_ids": projected_member_ids,
        "projected_representative_price": representative.geometry.value_at(decision_timestamp),
        "projected_representative_slope_per_second": representative.geometry.slope_per_second,
        "normalized_slope_atr_per_hour": None if source_atr is None else representative.geometry.slope_per_second * 3600.0 / source_atr,
        "projected_corridor_lower_price": min(prices),
        "projected_corridor_upper_price": max(prices),
        "projected_corridor_width_atr": (max(prices) - min(prices)) / normalization_context.atr,
        "source_confidence": family.confidence,
        "source_structural_importance": family.structural_importance,
        "source_event_id": None if event is None else event.event_id,
        "source_event_state": None if event is None else event.state.value,
        "source_age_seconds": reference.source_age_seconds,
        "source_age_bars": reference.source_age_bars,
        "source_bar_duration_seconds": reference.source_bar_duration_seconds,
        "freshness_state": reference.freshness_state.value,
        "contributes_to_confluence": reference.freshness_state is not MTFFreshnessState.STALE_EXCLUDED and source_atr is not None,
        "projected_order_changed": projected_order_changed,
        "projection_timestamp": decision_timestamp,
        "model_version": snapshot.model_version,
        "config_version": snapshot.config_version,
        "resolved_config_hash": snapshot.resolved_config_hash,
    }


def _corridor_overlap(left: ProjectedMTFFamily, right: ProjectedMTFFamily) -> float:
    lower = max(left.projected_corridor_lower_price, right.projected_corridor_lower_price)
    upper = min(left.projected_corridor_upper_price, right.projected_corridor_upper_price)
    overlap = max(upper - lower, 0.0)
    widths = (
        left.projected_corridor_upper_price - left.projected_corridor_lower_price,
        right.projected_corridor_upper_price - right.projected_corridor_lower_price,
    )
    if widths[0] == 0.0 and widths[1] == 0.0:
        return 1.0 if _close(left.projected_representative_price, right.projected_representative_price) else 0.0
    nonzero = [width for width in widths if width > 0.0]
    if overlap == 0.0:
        return 0.0
    return min(overlap / min(nonzero), 1.0)


def _level_separation(left: ProjectedMTFFamily, right: ProjectedMTFFamily, atr: float) -> float:
    return abs(left.projected_representative_price - right.projected_representative_price) / atr


def _corridor_separation(left: ProjectedMTFFamily, right: ProjectedMTFFamily, atr: float) -> float:
    return max(
        left.projected_corridor_lower_price - right.projected_corridor_upper_price,
        right.projected_corridor_lower_price - left.projected_corridor_upper_price,
        0.0,
    ) / atr


def _is_nested(left: ProjectedMTFFamily, right: ProjectedMTFFamily) -> bool:
    left_inside_right = left.projected_corridor_lower_price >= right.projected_corridor_lower_price and left.projected_corridor_upper_price <= right.projected_corridor_upper_price
    right_inside_left = right.projected_corridor_lower_price >= left.projected_corridor_lower_price and right.projected_corridor_upper_price <= left.projected_corridor_upper_price
    return (left_inside_right or right_inside_left) and not (
        _close(left.projected_corridor_lower_price, right.projected_corridor_lower_price)
        and _close(left.projected_corridor_upper_price, right.projected_corridor_upper_price)
    )


def _finite_intersection(
    left: LineGeometry,
    right: LineGeometry,
    *,
    decision_timestamp: datetime,
    horizon_seconds: float,
) -> tuple[datetime, float, float] | None:
    denominator = left.slope_per_second - right.slope_per_second
    if abs(denominator) <= 1e-15:
        return None
    left_reference = left.reference_time.timestamp()
    right_reference = right.reference_time.timestamp()
    seconds = (
        right.reference_price - left.reference_price
        + left.slope_per_second * left_reference
        - right.slope_per_second * right_reference
    ) / denominator
    if not math.isfinite(seconds):
        return None
    timestamp = datetime.fromtimestamp(seconds, tz=timezone.utc)
    delta = (timestamp - decision_timestamp).total_seconds()
    price = left.value_at(timestamp)
    if not math.isfinite(price) or delta < 0.0 or delta > horizon_seconds:
        return None
    return timestamp, delta, price


def _build_relations(
    *,
    families: tuple[ProjectedMTFFamily, ...],
    geometries: Mapping[str, LineGeometry],
    decision_timestamp: datetime,
    normalization_context: MTFNormalizationContext,
    policy: MTFPolicyAudit,
) -> tuple[MTFRelation, ...]:
    relations: list[MTFRelation] = []
    horizon = policy.intersection_horizon_bars * normalization_context.timeframe_duration_seconds
    for index, first in enumerate(families):
        for second in families[index + 1 :]:
            if first.source_timeframe == second.source_timeframe:
                continue
            left, right = sorted((first, second), key=lambda item: item.projected_family_id)
            level = _level_separation(left, right, normalization_context.atr)
            overlap = _corridor_overlap(left, right)
            separation = _corridor_separation(left, right, normalization_context.atr)
            slope = None if left.normalized_slope_atr_per_hour is None or right.normalized_slope_atr_per_hour is None else abs(left.normalized_slope_atr_per_hour - right.normalized_slope_atr_per_hour)
            intersection = _finite_intersection(
                geometries[left.projected_family_id], geometries[right.projected_family_id], decision_timestamp=decision_timestamp, horizon_seconds=horizon
            )
            stale = not left.contributes_to_confluence or not right.contributes_to_confluence
            compatible_slope = slope is not None and slope <= policy.max_slope_delta_atr_per_hour
            nearby = level <= policy.max_level_distance_atr
            corridor_nearby = overlap > 0.0 or separation <= policy.max_corridor_separation_atr
            conflict = left.source_family_role is not right.source_family_role and nearby and corridor_nearby
            if stale:
                relation_type, codes, severity = MTFRelationType.DISJOINT, ("stale_or_normalization_excluded",), None
            elif conflict:
                severity = min(1.0, (1.0 - min(level / max(policy.max_level_distance_atr, _FLOAT_TOLERANCE), 1.0)) * (0.5 + 0.5 * overlap))
                relation_type, codes = MTFRelationType.CONFLICT, ("opposite_role_nearby",)
            elif left.source_family_role is right.source_family_role and compatible_slope and nearby and _is_nested(left, right):
                relation_type, codes, severity = MTFRelationType.NESTED, ("same_role_nested_corridor",), None
            elif left.source_family_role is right.source_family_role and compatible_slope and nearby and corridor_nearby:
                relation_type = MTFRelationType.CONFLUENCE if overlap > 0.0 else MTFRelationType.AGREEMENT
                codes, severity = (("same_role_corridor_overlap",) if overlap > 0.0 else ("same_role_level_agreement",)), None
            elif left.source_family_role is right.source_family_role and slope is not None and slope > policy.max_slope_delta_atr_per_hour:
                relation_type, codes, severity = MTFRelationType.DIVERGENCE, ("same_role_slope_divergence",), None
            elif intersection is not None:
                relation_type, codes, severity = MTFRelationType.INTERSECTION, ("forward_exact_representative_intersection",), None
            else:
                relation_type, codes, severity = MTFRelationType.DISJOINT, ("no_compatible_relation",), None
            payload = {
                "relation_type": relation_type.value,
                "left_projected_family_id": left.projected_family_id,
                "right_projected_family_id": right.projected_family_id,
                "left_source_timeframe": left.source_timeframe,
                "right_source_timeframe": right.source_timeframe,
                "left_role": left.source_family_role.value,
                "right_role": right.source_family_role.value,
                "level_separation_atr": level,
                "corridor_overlap_ratio": overlap,
                "slope_disagreement_atr_per_hour": slope,
                "conflict_severity": severity,
                "intersection_timestamp": None if intersection is None else intersection[0],
                "intersection_seconds_from_decision": None if intersection is None else intersection[1],
                "intersection_price": None if intersection is None else intersection[2],
                "intersection_horizon_eligible": intersection is not None,
                "reason_codes": codes,
            }
            relations.append(MTFRelation(relation_id=deterministic_id("mtf-relation", payload), **payload))
    return tuple(sorted(relations, key=lambda item: item.relation_id))


def _build_clusters(
    *,
    families: tuple[ProjectedMTFFamily, ...],
    relations: tuple[MTFRelation, ...],
    decision_timestamp: datetime,
    normalization_context: MTFNormalizationContext,
    policy: MTFPolicyAudit,
    asset: str,
    model_version: str,
    config_version: str,
    mtf_config_hash: str,
) -> tuple[MTFCluster, ...]:
    compatible_pairs = {
        frozenset((relation.left_projected_family_id, relation.right_projected_family_id))
        for relation in relations
        if relation.relation_type in {MTFRelationType.AGREEMENT, MTFRelationType.CONFLUENCE, MTFRelationType.NESTED}
    }
    remaining = [
        family
        for family in families
        if family.contributes_to_confluence and family.source_family_lifecycle is FamilyLifecycleState.ACTIVE
    ]
    clusters: list[MTFCluster] = []
    while remaining:
        seed = remaining.pop(0)
        selected = [seed]
        for candidate in tuple(remaining):
            if candidate.source_family_role is not seed.source_family_role or candidate.source_timeframe in {item.source_timeframe for item in selected}:
                continue
            if all(frozenset((candidate.projected_family_id, member.projected_family_id)) in compatible_pairs for member in selected):
                selected.append(candidate)
                remaining.remove(candidate)
        clusters.append(
            _make_cluster(
                selected=tuple(sorted(selected, key=_projected_family_sort_key)),
                relations=relations,
                decision_timestamp=decision_timestamp,
                normalization_context=normalization_context,
                policy=policy,
                asset=asset,
                model_version=model_version,
                config_version=config_version,
                mtf_config_hash=mtf_config_hash,
            )
        )
    return tuple(sorted(clusters, key=lambda item: item.cluster_id))


def _make_cluster(
    *,
    selected: tuple[ProjectedMTFFamily, ...],
    relations: tuple[MTFRelation, ...],
    decision_timestamp: datetime,
    normalization_context: MTFNormalizationContext,
    policy: MTFPolicyAudit,
    asset: str,
    model_version: str,
    config_version: str,
    mtf_config_hash: str,
) -> MTFCluster:
    ids = tuple(sorted(item.projected_family_id for item in selected))
    by_pair = {
        frozenset((relation.left_projected_family_id, relation.right_projected_family_id)): relation
        for relation in relations
    }
    pair_relations = [
        by_pair[frozenset((left.projected_family_id, right.projected_family_id))]
        for index, left in enumerate(selected)
        for right in selected[index + 1 :]
    ]
    prices = [item.projected_representative_price for item in selected]
    slopes = [item.normalized_slope_atr_per_hour for item in selected]
    level_dispersion = None if len(selected) == 1 else (max(prices) - min(prices)) / normalization_context.atr
    slope_dispersion = None if len(selected) == 1 or any(item is None for item in slopes) else max(slopes) - min(slopes)
    overlap = None if not pair_relations else min(relation.corridor_overlap_ratio or 0.0 for relation in pair_relations)
    timeframe_count = len({item.source_timeframe for item in selected})
    is_confluence = timeframe_count >= policy.minimum_confluence_timeframes
    freshness_states = {item.freshness_state for item in selected}
    freshness_summary = next(iter(freshness_states)).value if len(freshness_states) == 1 else "MIXED"
    if len(selected) == 1:
        confluence_strength = None
    else:
        freshness_multiplier = 1.0 if freshness_states == {MTFFreshnessState.FRESH} else 0.75
        confidence = sum(item.source_confidence * item.source_structural_importance for item in selected) / len(selected)
        closeness = 1.0 - min((level_dispersion or 0.0) / max(policy.max_level_distance_atr, _FLOAT_TOLERANCE), 1.0)
        confluence_strength = min(1.0, max(0.0, confidence * closeness * freshness_multiplier))
    reference = min(
        selected,
        key=lambda item: (
            sum(abs(item.projected_representative_price - other.projected_representative_price) for other in selected),
            item.projected_family_id,
        ),
    )
    return _make_cluster_with_asset(
        selected=selected,
        ids=ids,
        decision_timestamp=decision_timestamp,
        normalization_context=normalization_context,
        asset=asset,
        model_version=model_version,
        config_version=config_version,
        mtf_config_hash=mtf_config_hash,
        reference=reference,
        level_dispersion=level_dispersion,
        slope_dispersion=slope_dispersion,
        overlap=overlap,
        confluence_strength=confluence_strength,
        is_confluence=is_confluence,
        freshness_summary=freshness_summary,
    )


def _make_cluster_with_asset(
    *,
    selected: tuple[ProjectedMTFFamily, ...],
    ids: tuple[str, ...],
    decision_timestamp: datetime,
    normalization_context: MTFNormalizationContext,
    asset: str,
    model_version: str,
    config_version: str,
    mtf_config_hash: str,
    reference: ProjectedMTFFamily,
    level_dispersion: float | None,
    slope_dispersion: float | None,
    overlap: float | None,
    confluence_strength: float | None,
    is_confluence: bool,
    freshness_summary: str,
) -> MTFCluster:
    timeframes = tuple(sorted({item.source_timeframe for item in selected}, key=_timeframe_key))
    prices = [item.projected_representative_price for item in selected]
    reason_codes = tuple(sorted({"complete_linkage_v1", "confluence" if is_confluence else "singleton_or_subthreshold"}))
    payload = {
        "asset": asset, "decision_timestamp": decision_timestamp, "role": selected[0].source_family_role.value,
        "projected_family_ids": ids, "source_timeframes": timeframes,
        "reference_projected_family_id": reference.projected_family_id, "timeframe_count": len(timeframes),
        "family_count": len(selected), "minimum_projected_price": min(prices), "maximum_projected_price": max(prices),
        "span_atr": (max(prices) - min(prices)) / normalization_context.atr,
        "representative_level_dispersion_atr": level_dispersion, "normalized_slope_dispersion": slope_dispersion,
        "corridor_overlap_ratio": overlap, "confluence_strength": confluence_strength, "is_confluence": is_confluence,
        "freshness_summary": freshness_summary, "model_version": model_version, "config_version": config_version,
        "resolved_config_hash": mtf_config_hash, "reason_codes": reason_codes,
    }
    return MTFCluster(cluster_id=deterministic_id("mtf-cluster", payload), **payload)


class LatestMTFSnapshotStore:
    """Small deterministic wrapper for independently arriving confirmed source snapshots."""

    def __init__(self, *, asset: str) -> None:
        self._asset = _text(asset, field_name="MTF store asset")
        self._snapshots: dict[str, TrendlineFamilySnapshot] = {}

    def update(self, snapshot: TrendlineFamilySnapshot) -> bool:
        if not isinstance(snapshot, TrendlineFamilySnapshot):
            raise ContractValidationError("MTF source update requires TrendlineFamilySnapshot")
        if snapshot.asset != self._asset:
            raise ContractValidationError("MTF source update asset mismatch")
        # Round-trip first: no caller-owned object reaches the latest-source head.
        canonical = TrendlineFamilySnapshot.from_dict(snapshot.to_dict())
        _validate_confirmed_phase_g_source(canonical)
        previous = self._snapshots.get(canonical.timeframe)
        if previous is not None:
            if canonical.snapshot_id == previous.snapshot_id:
                return False
            if canonical.timestamp <= previous.timestamp:
                raise ContractValidationError("older or conflicting MTF source snapshot cannot replace head")
            if canonical.previous_snapshot_id != previous.snapshot_id:
                raise ContractValidationError("MTF source update must continue the stored source lineage")
        self._snapshots[canonical.timeframe] = canonical
        return True

    def latest_sources(self) -> Mapping[str, TrendlineFamilySnapshot]:
        return MappingProxyType({
            timeframe: TrendlineFamilySnapshot.from_dict(snapshot.to_dict())
            for timeframe, snapshot in sorted(self._snapshots.items(), key=lambda item: _timeframe_key(item[0]))
        })

    def compose(
        self,
        *,
        decision_timestamp: datetime,
        normalization_context: MTFNormalizationContext,
        config: ResolvedTrendlineFamilyConfig,
    ) -> MTFGeometrySnapshot:
        return compose_mtf_snapshot(
            source_snapshots=self.latest_sources(),
            decision_timestamp=decision_timestamp,
            normalization_context=normalization_context,
            config=config,
        )


def build_mtf_shadow_features(snapshot: MTFGeometrySnapshot | None, *, enabled: bool = True) -> dict[str, Any]:
    """Project a persisted MTF snapshot into the additive shadow namespace only."""

    keys = (
        "enabled", "mtf_snapshot_id", "decision_timestamp", "source_timeframe_count", "fresh_source_count",
        "stale_included_source_count", "stale_excluded_source_count", "projected_family_count", "projected_member_count",
        "support_cluster_count", "resistance_cluster_count", "confluence_cluster_count", "conflict_relation_count",
        "agreement_relation_count", "intersection_relation_count", "nearest_support_mtf_cluster_id",
        "nearest_resistance_mtf_cluster_id", "nearest_conflict_relation_id", "support_confluence_strength",
        "resistance_confluence_strength", "support_timeframes", "resistance_timeframes", "source_snapshot_ids",
        "exclusion_reason_distribution", "source_timeframes", "source_age_bars", "cluster_family_sizes",
        "cluster_timeframe_counts", "confluence_strengths", "normalized_slope_dispersion_values",
        "corridor_overlap_ratio_values", "intersection_seconds_from_decision_values",
        "intersection_horizon_seconds_values",
    )
    if not enabled or snapshot is None:
        result = {key: None for key in keys}
        result["enabled"] = False
        result["source_snapshot_ids"] = ()
        for key in (
            "source_timeframes",
            "source_age_bars",
            "cluster_family_sizes",
            "cluster_timeframe_counts",
            "confluence_strengths",
            "normalized_slope_dispersion_values",
            "corridor_overlap_ratio_values",
            "intersection_seconds_from_decision_values",
            "intersection_horizon_seconds_values",
        ):
            result[key] = ()
        result["exclusion_reason_distribution"] = {}
        return result
    if not isinstance(snapshot, MTFGeometrySnapshot):
        raise ContractValidationError("MTF shadow features require MTFGeometrySnapshot")
    clusters = tuple(cluster for cluster in snapshot.clusters if cluster.is_confluence)
    support = _nearest_cluster(clusters, role=FamilyRole.SUPPORT, context=snapshot.normalization_context)
    resistance = _nearest_cluster(clusters, role=FamilyRole.RESISTANCE, context=snapshot.normalization_context)
    conflicts = tuple(relation for relation in snapshot.relations if relation.relation_type is MTFRelationType.CONFLICT)
    nearest_conflict = min(conflicts, key=lambda item: (item.level_separation_atr if item.level_separation_atr is not None else math.inf, item.relation_id), default=None)
    statuses = snapshot.source_statuses
    distribution: dict[str, int] = {}
    for status in statuses:
        for reason in status.reason_codes:
            distribution[reason] = distribution.get(reason, 0) + 1
    return {
        "enabled": True,
        "mtf_snapshot_id": snapshot.mtf_snapshot_id,
        "decision_timestamp": snapshot.decision_timestamp.isoformat(),
        "source_timeframe_count": len(snapshot.source_snapshots),
        "fresh_source_count": sum(item.freshness_state is MTFFreshnessState.FRESH for item in statuses),
        "stale_included_source_count": sum(item.freshness_state is MTFFreshnessState.STALE_INCLUDED for item in statuses),
        "stale_excluded_source_count": sum(item.freshness_state is MTFFreshnessState.STALE_EXCLUDED for item in statuses),
        "projected_family_count": len(snapshot.projected_families),
        "projected_member_count": len(snapshot.projected_members),
        "support_cluster_count": sum(item.role is FamilyRole.SUPPORT for item in snapshot.clusters),
        "resistance_cluster_count": sum(item.role is FamilyRole.RESISTANCE for item in snapshot.clusters),
        "confluence_cluster_count": len(clusters),
        "conflict_relation_count": len(conflicts),
        "agreement_relation_count": sum(item.relation_type is MTFRelationType.AGREEMENT for item in snapshot.relations),
        "intersection_relation_count": sum(item.intersection_horizon_eligible for item in snapshot.relations),
        "nearest_support_mtf_cluster_id": None if support is None else support.cluster_id,
        "nearest_resistance_mtf_cluster_id": None if resistance is None else resistance.cluster_id,
        "nearest_conflict_relation_id": None if nearest_conflict is None else nearest_conflict.relation_id,
        "support_confluence_strength": None if support is None else support.confluence_strength,
        "resistance_confluence_strength": None if resistance is None else resistance.confluence_strength,
        "support_timeframes": None if support is None else support.source_timeframes,
        "resistance_timeframes": None if resistance is None else resistance.source_timeframes,
        "source_snapshot_ids": tuple(item.source_snapshot_id for item in snapshot.source_snapshots),
        "exclusion_reason_distribution": dict(sorted(distribution.items())),
        "source_timeframes": tuple(item.source_timeframe for item in snapshot.source_snapshots),
        "source_age_bars": tuple(item.source_age_bars for item in snapshot.source_snapshots),
        "cluster_family_sizes": tuple(item.family_count for item in snapshot.clusters),
        "cluster_timeframe_counts": tuple(item.timeframe_count for item in snapshot.clusters),
        "confluence_strengths": tuple(item.confluence_strength for item in snapshot.clusters if item.confluence_strength is not None),
        "normalized_slope_dispersion_values": tuple(item.normalized_slope_dispersion for item in snapshot.clusters if item.normalized_slope_dispersion is not None),
        "corridor_overlap_ratio_values": tuple(item.corridor_overlap_ratio for item in snapshot.clusters if item.corridor_overlap_ratio is not None),
        "intersection_seconds_from_decision_values": tuple(item.intersection_seconds_from_decision for item in snapshot.relations if item.intersection_horizon_eligible),
        "intersection_horizon_seconds_values": tuple(
            snapshot.policy_audit.intersection_horizon_bars * snapshot.normalization_context.timeframe_duration_seconds
            for item in snapshot.relations
            if item.intersection_horizon_eligible
        ),
    }


def _nearest_cluster(
    clusters: Iterable[MTFCluster],
    *,
    role: FamilyRole,
    context: MTFNormalizationContext,
) -> MTFCluster | None:
    candidates = tuple(cluster for cluster in clusters if cluster.role is role)
    if not candidates or context.decision_price is None:
        return None
    return min(
        candidates,
        key=lambda item: (
            abs(((item.minimum_projected_price + item.maximum_projected_price) / 2.0) - context.decision_price),
            item.cluster_id,
        ),
    )
