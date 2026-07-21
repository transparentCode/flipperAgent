"""Causal, immutable, shadow-only multi-timeframe trendline composition.

This module projects already-confirmed single-timeframe snapshots.  It does
not create, refit, match, or mutate trendline families.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import math
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from ..configuration.contracts import (
    ResolvedTrendlineFamilyConfig,
    canonical_mtf_source_timeframes,
    canonical_timeframe_duration_seconds,
)
from ..domain.enums import FamilyLifecycleState, FamilyRole
from ..domain.geometry import LineGeometry
from ..domain.identity import deterministic_hash, deterministic_id
from ..domain.snapshots import (
    TrendlineFamilySnapshot,
    trendline_family_snapshot_has_phase_g_evidence,
    validate_trendline_family_snapshot_identity,
)
from ..domain.validation import ContractValidationError, parse_utc_isoformat, require_utc


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


def _validate_policy_source_timeframes(
    timeframes: Iterable[str],
    *,
    policy: "MTFPolicyAudit",
) -> None:
    unexpected = set(timeframes) - set(policy.source_timeframes)
    if unexpected:
        raise ContractValidationError(
            f"source timeframe is not configured for MTF: {sorted(unexpected)}"
        )


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
        from .relations import _corridor_overlap
        from .serialization import (
            _validate_mtf_snapshot_semantics,
            compute_mtf_snapshot_id,
        )

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
        from .serialization import _mtf_snapshot_identity_payload

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


def _validate_confirmed_phase_g_source(snapshot: TrendlineFamilySnapshot) -> None:
    if not trendline_family_snapshot_has_phase_g_evidence(snapshot):
        raise ContractValidationError(
            "MTF composition requires a canonical Phase-G source snapshot"
        )
    validate_trendline_family_snapshot_identity(snapshot)
    diagnostics = snapshot.diagnostics
    if (
        diagnostics.get("incomplete_bar") is True
        or diagnostics.get("is_incomplete") is True
        or diagnostics.get("confirmed_bar") is False
    ):
        raise ContractValidationError(
            "incomplete source snapshot cannot enter MTF composition"
        )


def _canonical_confirmed_phase_g_source_snapshot(
    snapshot: TrendlineFamilySnapshot,
) -> TrendlineFamilySnapshot:
    if not isinstance(snapshot, TrendlineFamilySnapshot):
        raise ContractValidationError(
            "MTF source audit requires TrendlineFamilySnapshot"
        )
    canonical = TrendlineFamilySnapshot.from_dict(snapshot.to_dict())
    _validate_confirmed_phase_g_source(canonical)
    return canonical
