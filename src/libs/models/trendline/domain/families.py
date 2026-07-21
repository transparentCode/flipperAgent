"""Canonical family, rail, corridor, and source-audit contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .candidates import LineCandidate, LineDiagnostics
from .enums import FamilyLifecycleState, FamilyRole, _lifecycle, _role
from .geometry import AnchorRef, LineGeometry
from .identity import deterministic_hash, deterministic_id
from .validation import (
    ContractValidationError,
    _decode,
    _hash,
    _integer,
    _interaction_close,
    _number,
    _optional_number,
    _primitive,
    _required,
    _string,
    _tuple_of_strings,
    parse_utc_isoformat,
    require_utc,
)

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
