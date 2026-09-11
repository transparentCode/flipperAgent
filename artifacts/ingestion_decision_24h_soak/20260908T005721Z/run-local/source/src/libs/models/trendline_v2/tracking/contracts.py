"""Immutable contracts for exact selected-structure tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from ..domain.candidates import LineCandidate
from ..domain.enums import AbstentionReason
from ..domain.identity import (
    deterministic_hash,
    provider_identity as canonical_provider_identity,
    require_hash,
)
from ..domain.validation import (
    ContractValidationError,
    parse_utc_isoformat,
    primitive,
    require_integer,
    require_string,
    require_utc,
)
from ..selection import SelectionStatus


TRACKING_POLICY_IDENTITY_NAMESPACE = "trendline_v2_tracking_policy"
TRACKED_FAMILY_IDENTITY_NAMESPACE = "trendline_v2_tracked_family"
TRANSITION_IDENTITY_NAMESPACE = "trendline_v2_family_tracking_transition"
TRACKING_SNAPSHOT_IDENTITY_NAMESPACE = "trendline_v2_tracking_snapshot"
SUPPORTED_SELECTION_POLICY_IDENTITY = (
    "3213d919e3e325b99ce156272759a42799bf296545b95c338ea803c087f99afc"
)
EXPECTED_TRACKING_POLICY_IDENTITY = (
    "82c026cadb53acd15f78e61e4773ff836574802dd0b82f130a80af32ee9353ce"
)


class TrackingStatus(str, Enum):
    UPDATED = "updated"
    SOURCE_UNAVAILABLE = "source_unavailable"


class FamilyTrackingTransitionType(str, Enum):
    BIRTH = "birth"
    CONTINUE = "continue"
    SOURCE_REMOVED = "source_removed"


def _require_optional_hash(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    return require_hash(value, field_name=field_name)


def _family_identity_payload(
    candidate: LineCandidate,
    *,
    provider_identity_value: str,
    discovery_config_identity: str,
    selection_policy_identity: str,
    tracking_policy_identity: str,
) -> dict[str, Any]:
    return {
        "asset": candidate.asset,
        "timeframe": candidate.timeframe,
        "role": candidate.role.value,
        "geometry": candidate.geometry.to_dict(),
        "anchors": [anchor.to_dict() for anchor in candidate.anchors],
        "evidence": candidate.evidence.to_dict(),
        "provider_identity": provider_identity_value,
        "discovery_config_identity": discovery_config_identity,
        "selection_policy_identity": selection_policy_identity,
        "tracking_policy_identity": tracking_policy_identity,
    }


def tracked_family_id(
    candidate: LineCandidate,
    *,
    provider_identity: str,
    discovery_config_identity: str,
    selection_policy_identity: str,
    tracking_policy_identity: str,
) -> str:
    """Return the stable identity of one exact structural candidate."""

    if not isinstance(candidate, LineCandidate):
        raise ContractValidationError("family identity candidate must be LineCandidate")
    provider_identity_value = require_hash(
        provider_identity, field_name="family.provider_identity"
    )
    discovery_config_identity = require_hash(
        discovery_config_identity, field_name="family.discovery_config_identity"
    )
    selection_policy_identity = require_hash(
        selection_policy_identity, field_name="family.selection_policy_identity"
    )
    tracking_policy_identity = require_hash(
        tracking_policy_identity, field_name="family.tracking_policy_identity"
    )
    if len(candidate.anchors) != 2:
        raise ContractValidationError("tracked family candidates require exactly two anchors")
    for anchor in candidate.anchors:
        require_hash(anchor.anchor_id, field_name="family.anchor_id")
    return deterministic_hash(
        TRACKED_FAMILY_IDENTITY_NAMESPACE,
        _family_identity_payload(
            candidate,
            provider_identity_value=provider_identity_value,
            discovery_config_identity=discovery_config_identity,
            selection_policy_identity=selection_policy_identity,
            tracking_policy_identity=tracking_policy_identity,
        ),
    )


@dataclass(frozen=True, slots=True)
class ExactSelectedStructureTrackingPolicy:
    """The single approved Phase 10A exact-lineage policy."""

    policy_name: str = "exact_selected_structure_lineage"
    policy_version: str = "v1"
    supported_selection_policy_identity: str = SUPPORTED_SELECTION_POLICY_IDENTITY

    def __post_init__(self) -> None:
        if require_string(self.policy_name, field_name="tracking.policy_name") != (
            "exact_selected_structure_lineage"
        ):
            raise ContractValidationError("tracking.policy_name is immutable")
        if require_string(self.policy_version, field_name="tracking.policy_version") != "v1":
            raise ContractValidationError("tracking.policy_version is immutable")
        supported = require_hash(
            self.supported_selection_policy_identity,
            field_name="tracking.supported_selection_policy_identity",
        )
        if supported != SUPPORTED_SELECTION_POLICY_IDENTITY:
            raise ContractValidationError(
                "tracking.supported_selection_policy_identity is immutable"
            )
        object.__setattr__(self, "policy_name", "exact_selected_structure_lineage")
        object.__setattr__(self, "policy_version", "v1")
        object.__setattr__(self, "supported_selection_policy_identity", supported)
        if self.policy_identity != EXPECTED_TRACKING_POLICY_IDENTITY:
            raise ContractValidationError("tracking policy identity is not canonical")

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "policy_version": self.policy_version,
            "supported_selection_policy_identity": self.supported_selection_policy_identity,
            "family_identity_fields": [
                "asset",
                "timeframe",
                "role",
                "geometry",
                "anchors",
                "evidence",
                "provider_identity",
                "discovery_config_identity",
                "selection_policy_identity",
                "tracking_policy_identity",
            ],
            "continuation_rule": "exact_family_id_match",
            "valid_source_absence_rule": "source_removed",
            "source_unavailable_rule": "carry_forward_without_observation",
            "removed_reappearance_rule": "reject",
            "observation_time_rule": "strictly_increasing",
        }

    @property
    def policy_identity(self) -> str:
        return deterministic_hash(TRACKING_POLICY_IDENTITY_NAMESPACE, self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExactSelectedStructureTrackingPolicy":
        if not isinstance(value, Mapping):
            raise ContractValidationError("tracking policy payload must be a mapping")
        expected = {
            "policy_name",
            "policy_version",
            "supported_selection_policy_identity",
            "family_identity_fields",
            "continuation_rule",
            "valid_source_absence_rule",
            "source_unavailable_rule",
            "removed_reappearance_rule",
            "observation_time_rule",
        }
        if set(value) != expected:
            raise ContractValidationError("tracking policy payload keys mismatch")
        expected_fields = [
            "asset",
            "timeframe",
            "role",
            "geometry",
            "anchors",
            "evidence",
            "provider_identity",
            "discovery_config_identity",
            "selection_policy_identity",
            "tracking_policy_identity",
        ]
        if value["family_identity_fields"] != expected_fields:
            raise ContractValidationError("tracking family identity fields are immutable")
        expected_values = {
            "continuation_rule": "exact_family_id_match",
            "valid_source_absence_rule": "source_removed",
            "source_unavailable_rule": "carry_forward_without_observation",
            "removed_reappearance_rule": "reject",
            "observation_time_rule": "strictly_increasing",
        }
        if any(value[key] != expected for key, expected in expected_values.items()):
            raise ContractValidationError("tracking policy semantics are immutable")
        result = cls(
            policy_name=value["policy_name"],
            policy_version=value["policy_version"],
            supported_selection_policy_identity=value[
                "supported_selection_policy_identity"
            ],
        )
        if result.to_dict() != dict(value):
            raise ContractValidationError("tracking policy payload is not canonical")
        return result


@dataclass(frozen=True, slots=True)
class TrackedTrendlineFamily:
    family_id: str
    version: int
    first_seen_at: datetime
    last_seen_at: datetime
    observation_count: int
    current_candidate: LineCandidate
    current_selection_snapshot_id: str
    provider_identity: str
    discovery_config_identity: str
    selection_policy_identity: str
    tracking_policy_identity: str

    def __post_init__(self) -> None:
        family_id = require_hash(self.family_id, field_name="family.family_id")
        version = require_integer(self.version, field_name="family.version", minimum=1)
        first_seen = require_utc(self.first_seen_at, field_name="family.first_seen_at")
        last_seen = require_utc(self.last_seen_at, field_name="family.last_seen_at")
        observation_count = require_integer(
            self.observation_count, field_name="family.observation_count", minimum=1
        )
        if version != observation_count:
            raise ContractValidationError("family version must equal observation count")
        if first_seen > last_seen:
            raise ContractValidationError("family first_seen_at must not exceed last_seen_at")
        if not isinstance(self.current_candidate, LineCandidate):
            raise ContractValidationError("family current_candidate must be LineCandidate")
        if len(self.current_candidate.anchors) != 2:
            raise ContractValidationError("tracked family requires exactly two anchors")
        if last_seen != self.current_candidate.observed_at:
            raise ContractValidationError("family last_seen_at must match candidate observation")
        snapshot_id = require_hash(
            self.current_selection_snapshot_id,
            field_name="family.current_selection_snapshot_id",
        )
        provider_identity_value = require_hash(
            self.provider_identity, field_name="family.provider_identity"
        )
        discovery_config_identity = require_hash(
            self.discovery_config_identity, field_name="family.discovery_config_identity"
        )
        selection_policy_identity = require_hash(
            self.selection_policy_identity, field_name="family.selection_policy_identity"
        )
        tracking_policy_identity = require_hash(
            self.tracking_policy_identity, field_name="family.tracking_policy_identity"
        )
        if canonical_provider_identity(self.current_candidate.provider_name, self.current_candidate.provider_version) != provider_identity_value:
            raise ContractValidationError("family provider identity mismatch")
        if any(not require_hash(anchor.anchor_id, field_name="family.anchor_id") for anchor in self.current_candidate.anchors):
            raise ContractValidationError("family anchor identity is invalid")
        if tracked_family_id(
            self.current_candidate,
            provider_identity=provider_identity_value,
            discovery_config_identity=discovery_config_identity,
            selection_policy_identity=selection_policy_identity,
            tracking_policy_identity=tracking_policy_identity,
        ) != family_id:
            raise ContractValidationError("family_id does not match canonical content")
        object.__setattr__(self, "family_id", family_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "first_seen_at", first_seen)
        object.__setattr__(self, "last_seen_at", last_seen)
        object.__setattr__(self, "observation_count", observation_count)
        object.__setattr__(self, "current_selection_snapshot_id", snapshot_id)
        object.__setattr__(self, "provider_identity", provider_identity_value)
        object.__setattr__(self, "discovery_config_identity", discovery_config_identity)
        object.__setattr__(self, "selection_policy_identity", selection_policy_identity)
        object.__setattr__(self, "tracking_policy_identity", tracking_policy_identity)

    def to_dict(self) -> dict[str, Any]:
        return primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrackedTrendlineFamily":
        if not isinstance(value, Mapping):
            raise ContractValidationError("family payload must be a mapping")
        expected = {
            "family_id",
            "version",
            "first_seen_at",
            "last_seen_at",
            "observation_count",
            "current_candidate",
            "current_selection_snapshot_id",
            "provider_identity",
            "discovery_config_identity",
            "selection_policy_identity",
            "tracking_policy_identity",
        }
        if set(value) != expected:
            raise ContractValidationError("family payload keys mismatch")
        try:
            return cls(
                family_id=value["family_id"],
                version=value["version"],
                first_seen_at=parse_utc_isoformat(
                    value["first_seen_at"], field_name="family.first_seen_at"
                ),
                last_seen_at=parse_utc_isoformat(
                    value["last_seen_at"], field_name="family.last_seen_at"
                ),
                observation_count=value["observation_count"],
                current_candidate=LineCandidate.from_dict(value["current_candidate"]),
                current_selection_snapshot_id=value["current_selection_snapshot_id"],
                provider_identity=value["provider_identity"],
                discovery_config_identity=value["discovery_config_identity"],
                selection_policy_identity=value["selection_policy_identity"],
                tracking_policy_identity=value["tracking_policy_identity"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid family payload") from exc


@dataclass(frozen=True, slots=True)
class FamilyTrackingTransition:
    transition_id: str
    family_id: str
    transition_type: FamilyTrackingTransitionType | str
    observed_at: datetime
    previous_family_version: int | None
    current_family_version: int | None
    previous_candidate_id: str | None
    current_candidate_id: str | None
    previous_selection_snapshot_id: str | None
    current_selection_snapshot_id: str | None
    tracking_policy_identity: str

    def __post_init__(self) -> None:
        transition_id = require_hash(self.transition_id, field_name="transition.transition_id")
        family_id = require_hash(self.family_id, field_name="transition.family_id")
        try:
            transition_type = FamilyTrackingTransitionType(self.transition_type)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("invalid family transition type") from exc
        observed = require_utc(self.observed_at, field_name="transition.observed_at")
        previous_version = self.previous_family_version
        current_version = self.current_family_version
        if previous_version is not None:
            previous_version = require_integer(
                previous_version, field_name="transition.previous_family_version", minimum=1
            )
        if current_version is not None:
            current_version = require_integer(
                current_version, field_name="transition.current_family_version", minimum=1
            )
        previous_candidate_id = _require_optional_hash(
            self.previous_candidate_id, field_name="transition.previous_candidate_id"
        )
        current_candidate_id = _require_optional_hash(
            self.current_candidate_id, field_name="transition.current_candidate_id"
        )
        previous_snapshot_id = _require_optional_hash(
            self.previous_selection_snapshot_id,
            field_name="transition.previous_selection_snapshot_id",
        )
        current_snapshot_id = _require_optional_hash(
            self.current_selection_snapshot_id,
            field_name="transition.current_selection_snapshot_id",
        )
        if transition_type is FamilyTrackingTransitionType.BIRTH:
            valid = (
                previous_version is None
                and current_version == 1
                and previous_candidate_id is None
                and current_candidate_id is not None
                and previous_snapshot_id is None
                and current_snapshot_id is not None
            )
        elif transition_type is FamilyTrackingTransitionType.CONTINUE:
            valid = (
                previous_version is not None
                and current_version == previous_version + 1
                and previous_candidate_id is not None
                and current_candidate_id is not None
                and previous_snapshot_id is not None
                and current_snapshot_id is not None
                and previous_candidate_id != current_candidate_id
                and previous_snapshot_id != current_snapshot_id
            )
        else:
            valid = (
                previous_version is not None
                and current_version is None
                and previous_candidate_id is not None
                and current_candidate_id is None
                and previous_snapshot_id is not None
                and current_snapshot_id is not None
                and previous_snapshot_id != current_snapshot_id
            )
        if not valid:
            raise ContractValidationError("invalid family transition field combination")
        tracking_policy_identity = require_hash(
            self.tracking_policy_identity,
            field_name="transition.tracking_policy_identity",
        )
        object.__setattr__(self, "transition_id", transition_id)
        object.__setattr__(self, "family_id", family_id)
        object.__setattr__(self, "transition_type", transition_type)
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "previous_family_version", previous_version)
        object.__setattr__(self, "current_family_version", current_version)
        object.__setattr__(self, "previous_candidate_id", previous_candidate_id)
        object.__setattr__(self, "current_candidate_id", current_candidate_id)
        object.__setattr__(self, "previous_selection_snapshot_id", previous_snapshot_id)
        object.__setattr__(self, "current_selection_snapshot_id", current_snapshot_id)
        object.__setattr__(self, "tracking_policy_identity", tracking_policy_identity)
        if self.expected_transition_id != transition_id:
            raise ContractValidationError("transition_id does not match canonical content")

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "transition_type": self.transition_type.value,
            "observed_at": self.observed_at,
            "previous_family_version": self.previous_family_version,
            "current_family_version": self.current_family_version,
            "previous_candidate_id": self.previous_candidate_id,
            "current_candidate_id": self.current_candidate_id,
            "previous_selection_snapshot_id": self.previous_selection_snapshot_id,
            "current_selection_snapshot_id": self.current_selection_snapshot_id,
            "tracking_policy_identity": self.tracking_policy_identity,
        }

    @property
    def expected_transition_id(self) -> str:
        return deterministic_hash(TRANSITION_IDENTITY_NAMESPACE, self._identity_payload())

    @classmethod
    def create(
        cls,
        *,
        family_id: str,
        transition_type: FamilyTrackingTransitionType | str,
        observed_at: datetime,
        previous_family_version: int | None,
        current_family_version: int | None,
        previous_candidate_id: str | None,
        current_candidate_id: str | None,
        previous_selection_snapshot_id: str | None,
        current_selection_snapshot_id: str | None,
        tracking_policy_identity: str,
    ) -> "FamilyTrackingTransition":
        role = FamilyTrackingTransitionType(transition_type)
        payload = {
            "family_id": family_id,
            "transition_type": role.value,
            "observed_at": require_utc(observed_at),
            "previous_family_version": previous_family_version,
            "current_family_version": current_family_version,
            "previous_candidate_id": previous_candidate_id,
            "current_candidate_id": current_candidate_id,
            "previous_selection_snapshot_id": previous_selection_snapshot_id,
            "current_selection_snapshot_id": current_selection_snapshot_id,
            "tracking_policy_identity": tracking_policy_identity,
        }
        return cls(
            transition_id=deterministic_hash(TRANSITION_IDENTITY_NAMESPACE, payload),
            **payload,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"transition_id": self.transition_id, **primitive(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilyTrackingTransition":
        if not isinstance(value, Mapping):
            raise ContractValidationError("transition payload must be a mapping")
        expected = {
            "transition_id",
            "family_id",
            "transition_type",
            "observed_at",
            "previous_family_version",
            "current_family_version",
            "previous_candidate_id",
            "current_candidate_id",
            "previous_selection_snapshot_id",
            "current_selection_snapshot_id",
            "tracking_policy_identity",
        }
        if set(value) != expected:
            raise ContractValidationError("transition payload keys mismatch")
        try:
            return cls(
                transition_id=value["transition_id"],
                family_id=value["family_id"],
                transition_type=value["transition_type"],
                observed_at=parse_utc_isoformat(
                    value["observed_at"], field_name="transition.observed_at"
                ),
                previous_family_version=value["previous_family_version"],
                current_family_version=value["current_family_version"],
                previous_candidate_id=value["previous_candidate_id"],
                current_candidate_id=value["current_candidate_id"],
                previous_selection_snapshot_id=value["previous_selection_snapshot_id"],
                current_selection_snapshot_id=value["current_selection_snapshot_id"],
                tracking_policy_identity=value["tracking_policy_identity"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid transition payload") from exc


@dataclass(frozen=True, slots=True)
class TrackingDiagnostics:
    previous_active_count: int
    source_selected_candidate_count: int
    current_active_count: int
    birth_count: int
    continuation_count: int
    source_removed_count: int
    carried_forward_count: int
    cumulative_removed_count: int

    def __post_init__(self) -> None:
        for field_name in (
            "previous_active_count",
            "source_selected_candidate_count",
            "current_active_count",
            "birth_count",
            "continuation_count",
            "source_removed_count",
            "carried_forward_count",
            "cumulative_removed_count",
        ):
            object.__setattr__(
                self,
                field_name,
                require_integer(
                    getattr(self, field_name),
                    field_name=f"tracking.diagnostics.{field_name}",
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrackingDiagnostics":
        if not isinstance(value, Mapping):
            raise ContractValidationError("tracking diagnostics payload must be a mapping")
        expected = {
            "previous_active_count",
            "source_selected_candidate_count",
            "current_active_count",
            "birth_count",
            "continuation_count",
            "source_removed_count",
            "carried_forward_count",
            "cumulative_removed_count",
        }
        if set(value) != expected:
            raise ContractValidationError("tracking diagnostics payload keys mismatch")
        try:
            return cls(**dict(value))
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid tracking diagnostics payload") from exc


@dataclass(frozen=True, slots=True)
class TrendlineTrackingSnapshot:
    asset: str
    timeframe: str
    observed_at: datetime
    previous_tracking_snapshot_id: str | None
    source_selection_snapshot_id: str
    input_identity: str
    discovery_config_identity: str
    provider_identity: str
    selection_policy_identity: str
    tracking_policy_identity: str
    status: TrackingStatus | str
    source_selection_status: SelectionStatus | str
    source_reason: AbstentionReason | str | None
    active_families: tuple[TrackedTrendlineFamily, ...]
    removed_family_ids: tuple[str, ...]
    transitions: tuple[FamilyTrackingTransition, ...]
    diagnostics: TrackingDiagnostics

    def __post_init__(self) -> None:
        asset = require_string(self.asset, field_name="tracking.asset")
        timeframe = require_string(self.timeframe, field_name="tracking.timeframe")
        observed = require_utc(self.observed_at, field_name="tracking.observed_at")
        previous_snapshot_id = _require_optional_hash(
            self.previous_tracking_snapshot_id,
            field_name="tracking.previous_tracking_snapshot_id",
        )
        source_selection_snapshot_id = require_hash(
            self.source_selection_snapshot_id,
            field_name="tracking.source_selection_snapshot_id",
        )
        input_identity = require_hash(self.input_identity, field_name="tracking.input_identity")
        discovery_config_identity = require_hash(
            self.discovery_config_identity,
            field_name="tracking.discovery_config_identity",
        )
        provider_identity_value = require_hash(
            self.provider_identity, field_name="tracking.provider_identity"
        )
        selection_policy_identity = require_hash(
            self.selection_policy_identity,
            field_name="tracking.selection_policy_identity",
        )
        tracking_policy_identity = require_hash(
            self.tracking_policy_identity,
            field_name="tracking.tracking_policy_identity",
        )
        try:
            status = TrackingStatus(self.status)
            source_status = SelectionStatus(self.source_selection_status)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("invalid tracking status") from exc
        reason = None
        if self.source_reason is not None:
            try:
                reason = AbstentionReason(self.source_reason)
            except (TypeError, ValueError) as exc:
                raise ContractValidationError("invalid tracking source reason") from exc
        if status is TrackingStatus.UPDATED:
            if source_status is not SelectionStatus.SELECTED or reason is not None:
                raise ContractValidationError("updated tracking requires selected source")
        else:
            if source_status is SelectionStatus.SELECTED or reason is None:
                raise ContractValidationError(
                    "unavailable tracking requires unavailable source reason"
                )
            if (
                source_status is SelectionStatus.SOURCE_FAILED
                and reason is not AbstentionReason.PROVIDER_FAILURE
            ):
                raise ContractValidationError("failed source requires provider_failure")
            if (
                source_status is SelectionStatus.SOURCE_ABSTAINED
                and reason is AbstentionReason.PROVIDER_FAILURE
            ):
                raise ContractValidationError(
                    "abstained source cannot use provider_failure"
                )
        if not isinstance(self.active_families, tuple):
            raise ContractValidationError("active families must be a tuple")
        if not isinstance(self.removed_family_ids, tuple):
            raise ContractValidationError("removed family IDs must be a tuple")
        if not isinstance(self.transitions, tuple):
            raise ContractValidationError("tracking transitions must be a tuple")
        if not isinstance(self.diagnostics, TrackingDiagnostics):
            raise ContractValidationError("tracking diagnostics must be TrackingDiagnostics")
        active = self.active_families
        if any(not isinstance(family, TrackedTrendlineFamily) for family in active):
            raise ContractValidationError("active families must be TrackedTrendlineFamily values")
        active_ids = tuple(family.family_id for family in active)
        if len(set(active_ids)) != len(active_ids):
            raise ContractValidationError("active family IDs must be unique")
        if active_ids != tuple(sorted(active_ids)):
            raise ContractValidationError("active families must use canonical ordering")
        removed = tuple(
            require_hash(family_id, field_name="tracking.removed_family_id")
            for family_id in self.removed_family_ids
        )
        if len(set(removed)) != len(removed):
            raise ContractValidationError("removed family IDs must be unique")
        if removed != tuple(sorted(removed)):
            raise ContractValidationError("removed family IDs must use canonical ordering")
        if set(active_ids) & set(removed):
            raise ContractValidationError("active and removed family IDs must be disjoint")
        active_by_id = {family.family_id: family for family in active}
        transitions = self.transitions
        if any(not isinstance(item, FamilyTrackingTransition) for item in transitions):
            raise ContractValidationError("tracking transitions must be transition values")
        transition_ids = tuple(item.family_id for item in transitions)
        if len(set(transition_ids)) != len(transition_ids):
            raise ContractValidationError("transition family IDs must be unique")
        if transition_ids != tuple(sorted(transition_ids)):
            raise ContractValidationError("tracking transitions must use canonical ordering")
        for family in active:
            if (
                family.current_candidate.asset != asset
                or family.current_candidate.timeframe != timeframe
                or family.provider_identity != provider_identity_value
                or family.discovery_config_identity != discovery_config_identity
                or family.selection_policy_identity != selection_policy_identity
                or family.tracking_policy_identity != tracking_policy_identity
            ):
                raise ContractValidationError("active family identity mismatch")
            if status is TrackingStatus.UPDATED and family.last_seen_at != observed:
                raise ContractValidationError("updated family observation boundary mismatch")
            if (
                status is TrackingStatus.UPDATED
                and family.current_selection_snapshot_id != source_selection_snapshot_id
            ):
                raise ContractValidationError(
                    "updated family selection snapshot does not match tracking source"
                )
            if (
                status is TrackingStatus.SOURCE_UNAVAILABLE
                and family.current_selection_snapshot_id == source_selection_snapshot_id
            ):
                raise ContractValidationError(
                    "carried family cannot bind to unavailable source snapshot"
                )
        for transition in transitions:
            if (
                transition.tracking_policy_identity != tracking_policy_identity
                or transition.observed_at != observed
            ):
                raise ContractValidationError("transition snapshot binding mismatch")
            if transition.transition_type in (
                FamilyTrackingTransitionType.BIRTH,
                FamilyTrackingTransitionType.CONTINUE,
            ):
                family = active_by_id.get(transition.family_id)
                if family is None:
                    raise ContractValidationError("transition current family is missing")
                if (
                    transition.current_candidate_id != family.current_candidate.candidate_id
                    or transition.current_family_version != family.version
                    or transition.current_selection_snapshot_id
                    != source_selection_snapshot_id
                ):
                    raise ContractValidationError("transition current family binding mismatch")
            elif transition.family_id in active_by_id or transition.family_id not in set(removed):
                raise ContractValidationError("source-removed transition family binding mismatch")
        diagnostics = self.diagnostics
        if previous_snapshot_id is None:
            if diagnostics.previous_active_count != 0:
                raise ContractValidationError(
                    "initial tracking snapshot cannot have previous active families"
                )
            if removed or diagnostics.cumulative_removed_count != 0:
                raise ContractValidationError(
                    "initial tracking snapshot cannot contain removed families"
                )
            if (
                diagnostics.continuation_count != 0
                or diagnostics.source_removed_count != 0
            ):
                raise ContractValidationError(
                    "initial tracking snapshot cannot contain non-birth transitions"
                )
        if status is TrackingStatus.UPDATED:
            self._validate_updated(
                active_ids=active_ids,
                removed=removed,
                transitions=transitions,
                diagnostics=diagnostics,
                source_selection_snapshot_id=source_selection_snapshot_id,
            )
        else:
            self._validate_unavailable(
                active_ids=active_ids,
                active_families=active,
                observed_at=observed,
                removed=removed,
                transitions=transitions,
                diagnostics=diagnostics,
            )
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "previous_tracking_snapshot_id", previous_snapshot_id)
        object.__setattr__(self, "source_selection_snapshot_id", source_selection_snapshot_id)
        object.__setattr__(self, "input_identity", input_identity)
        object.__setattr__(self, "discovery_config_identity", discovery_config_identity)
        object.__setattr__(self, "provider_identity", provider_identity_value)
        object.__setattr__(self, "selection_policy_identity", selection_policy_identity)
        object.__setattr__(self, "tracking_policy_identity", tracking_policy_identity)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "source_selection_status", source_status)
        object.__setattr__(self, "source_reason", reason)
        object.__setattr__(self, "active_families", active)
        object.__setattr__(self, "removed_family_ids", removed)
        object.__setattr__(self, "transitions", transitions)

    @staticmethod
    def _validate_updated(
        *,
        active_ids: tuple[str, ...],
        removed: tuple[str, ...],
        transitions: tuple[FamilyTrackingTransition, ...],
        diagnostics: TrackingDiagnostics,
        source_selection_snapshot_id: str,
    ) -> None:
        if diagnostics.current_active_count != len(active_ids):
            raise ContractValidationError("updated current active count mismatch")
        if diagnostics.source_selected_candidate_count != len(active_ids):
            raise ContractValidationError("updated source selected count mismatch")
        if diagnostics.birth_count + diagnostics.continuation_count != len(active_ids):
            raise ContractValidationError("updated birth/continuation arithmetic mismatch")
        if diagnostics.continuation_count + diagnostics.source_removed_count != diagnostics.previous_active_count:
            raise ContractValidationError("updated previous active arithmetic mismatch")
        if diagnostics.carried_forward_count != 0:
            raise ContractValidationError("updated snapshot cannot carry families forward")
        if diagnostics.cumulative_removed_count != len(removed):
            raise ContractValidationError("updated cumulative removal count mismatch")
        transition_by_type = {
            transition_type: {item.family_id for item in transitions if item.transition_type is transition_type}
            for transition_type in FamilyTrackingTransitionType
        }
        birth_ids = transition_by_type[FamilyTrackingTransitionType.BIRTH]
        continue_ids = transition_by_type[FamilyTrackingTransitionType.CONTINUE]
        removed_ids = transition_by_type[FamilyTrackingTransitionType.SOURCE_REMOVED]
        current_ids = set(active_ids)
        previous_ids = continue_ids | removed_ids
        if birth_ids | continue_ids != current_ids or birth_ids & continue_ids:
            raise ContractValidationError("updated transition/current family coverage mismatch")
        if len(previous_ids) != diagnostics.previous_active_count:
            raise ContractValidationError("updated transition/previous family coverage mismatch")
        if not removed_ids.issubset(set(removed)):
            raise ContractValidationError("source-removed families must be cumulative removed IDs")
        if len(birth_ids) != diagnostics.birth_count:
            raise ContractValidationError("updated birth diagnostic mismatch")
        if len(continue_ids) != diagnostics.continuation_count:
            raise ContractValidationError("updated continuation diagnostic mismatch")
        if len(removed_ids) != diagnostics.source_removed_count:
            raise ContractValidationError("updated removal diagnostic mismatch")
        for transition in transitions:
            if transition.transition_type in (
                FamilyTrackingTransitionType.BIRTH,
                FamilyTrackingTransitionType.CONTINUE,
            ) and transition.current_selection_snapshot_id != source_selection_snapshot_id:
                raise ContractValidationError("current transition source snapshot mismatch")
            if transition.transition_type is FamilyTrackingTransitionType.SOURCE_REMOVED and transition.current_selection_snapshot_id != source_selection_snapshot_id:
                raise ContractValidationError("removal transition source snapshot mismatch")

    @staticmethod
    def _validate_unavailable(
        *,
        active_ids: tuple[str, ...],
        active_families: tuple[TrackedTrendlineFamily, ...],
        observed_at: datetime,
        removed: tuple[str, ...],
        transitions: tuple[FamilyTrackingTransition, ...],
        diagnostics: TrackingDiagnostics,
    ) -> None:
        if transitions:
            raise ContractValidationError("source-unavailable snapshot cannot have transitions")
        if diagnostics.source_selected_candidate_count != 0:
            raise ContractValidationError("source-unavailable snapshot selected count must be zero")
        if diagnostics.current_active_count != len(active_ids):
            raise ContractValidationError("source-unavailable current active count mismatch")
        if diagnostics.current_active_count != diagnostics.previous_active_count:
            raise ContractValidationError("source-unavailable active count must carry forward")
        if any(family.last_seen_at >= observed_at for family in active_families):
            raise ContractValidationError(
                "carried family must precede unavailable observation"
            )
        if any(
            value != 0
            for value in (
                diagnostics.birth_count,
                diagnostics.continuation_count,
                diagnostics.source_removed_count,
            )
        ):
            raise ContractValidationError("source-unavailable snapshot cannot mutate families")
        if diagnostics.carried_forward_count != diagnostics.previous_active_count:
            raise ContractValidationError("source-unavailable carry-forward count mismatch")
        if diagnostics.cumulative_removed_count != len(removed):
            raise ContractValidationError("source-unavailable cumulative removal count mismatch")

    @property
    def snapshot_id(self) -> str:
        return deterministic_hash(
            TRACKING_SNAPSHOT_IDENTITY_NAMESPACE,
            self._identity_payload(),
        )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "observed_at": self.observed_at,
            "previous_tracking_snapshot_id": self.previous_tracking_snapshot_id,
            "source_selection_snapshot_id": self.source_selection_snapshot_id,
            "input_identity": self.input_identity,
            "discovery_config_identity": self.discovery_config_identity,
            "provider_identity": self.provider_identity,
            "selection_policy_identity": self.selection_policy_identity,
            "tracking_policy_identity": self.tracking_policy_identity,
            "status": self.status.value,
            "source_selection_status": self.source_selection_status.value,
            "source_reason": self.source_reason.value if self.source_reason is not None else None,
            "active_families": [family.to_dict() for family in self.active_families],
            "removed_family_ids": list(self.removed_family_ids),
            "transitions": [transition.to_dict() for transition in self.transitions],
            "diagnostics": self.diagnostics.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id, **primitive(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrendlineTrackingSnapshot":
        if not isinstance(value, Mapping):
            raise ContractValidationError("tracking snapshot payload must be a mapping")
        expected = {
            "snapshot_id",
            "asset",
            "timeframe",
            "observed_at",
            "previous_tracking_snapshot_id",
            "source_selection_snapshot_id",
            "input_identity",
            "discovery_config_identity",
            "provider_identity",
            "selection_policy_identity",
            "tracking_policy_identity",
            "status",
            "source_selection_status",
            "source_reason",
            "active_families",
            "removed_family_ids",
            "transitions",
            "diagnostics",
        }
        if set(value) != expected:
            raise ContractValidationError("tracking snapshot payload keys mismatch")
        if not all(isinstance(value[key], list) for key in ("active_families", "removed_family_ids", "transitions")):
            raise ContractValidationError("tracking snapshot collections must be lists")
        try:
            result = cls(
                asset=value["asset"],
                timeframe=value["timeframe"],
                observed_at=parse_utc_isoformat(value["observed_at"], field_name="tracking.observed_at"),
                previous_tracking_snapshot_id=value["previous_tracking_snapshot_id"],
                source_selection_snapshot_id=value["source_selection_snapshot_id"],
                input_identity=value["input_identity"],
                discovery_config_identity=value["discovery_config_identity"],
                provider_identity=value["provider_identity"],
                selection_policy_identity=value["selection_policy_identity"],
                tracking_policy_identity=value["tracking_policy_identity"],
                status=value["status"],
                source_selection_status=value["source_selection_status"],
                source_reason=value["source_reason"],
                active_families=tuple(
                    TrackedTrendlineFamily.from_dict(item) for item in value["active_families"]
                ),
                removed_family_ids=tuple(value["removed_family_ids"]),
                transitions=tuple(
                    FamilyTrackingTransition.from_dict(item) for item in value["transitions"]
                ),
                diagnostics=TrackingDiagnostics.from_dict(value["diagnostics"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid tracking snapshot payload") from exc
        if value["snapshot_id"] != result.snapshot_id:
            raise ContractValidationError("tracking snapshot_id does not match canonical content")
        return result


__all__ = [
    "EXPECTED_TRACKING_POLICY_IDENTITY",
    "ExactSelectedStructureTrackingPolicy",
    "FamilyTrackingTransition",
    "FamilyTrackingTransitionType",
    "SUPPORTED_SELECTION_POLICY_IDENTITY",
    "TrackedTrendlineFamily",
    "TrackingDiagnostics",
    "TrackingStatus",
    "TrendlineTrackingSnapshot",
    "tracked_family_id",
]
