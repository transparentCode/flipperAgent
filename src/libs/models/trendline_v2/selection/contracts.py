"""Immutable contracts for explicit Trendline V2 candidate selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from ..domain.candidates import LineCandidate
from ..domain.enums import AbstentionReason, LineRole
from ..domain.identity import deterministic_hash, provider_identity, require_hash
from ..domain.validation import (
    ContractValidationError,
    parse_utc_isoformat,
    primitive,
    require_integer,
    require_string,
    require_utc,
)


POLICY_IDENTITY_NAMESPACE = "trendline_v2_candidate_selection_policy"
DECISION_IDENTITY_NAMESPACE = "trendline_v2_candidate_selection_decision"
SNAPSHOT_IDENTITY_NAMESPACE = "trendline_v2_candidate_selection_snapshot"
CANDIDATE_SET_IDENTITY_NAMESPACE = "trendline_v2_candidate_set"


class SelectionStatus(str, Enum):
    """Selection result status, including source-outcome pass-through."""

    SELECTED = "selected"
    SOURCE_ABSTAINED = "source_abstained"
    SOURCE_FAILED = "source_failed"


def candidate_set_identity(candidate_ids: tuple[str, ...] | list[str]) -> str:
    """Return the identity of a complete, lexicographically ordered ID set."""

    ids = tuple(candidate_ids)
    if any(not isinstance(candidate_id, str) for candidate_id in ids):
        raise ContractValidationError("candidate IDs must be strings")
    canonical_ids = tuple(require_hash(candidate_id, field_name="candidate_id") for candidate_id in ids)
    if len(set(canonical_ids)) != len(canonical_ids):
        raise ContractValidationError("candidate IDs must be unique")
    return deterministic_hash(
        CANDIDATE_SET_IDENTITY_NAMESPACE,
        {"candidate_ids": sorted(canonical_ids)},
    )


@dataclass(frozen=True, slots=True)
class LatestValidPredecessorPolicy:
    """The single explicit Phase 9D selection policy."""

    policy_name: str = "latest_valid_predecessor"
    policy_version: str = "v1"
    research_family_id: str = "latest_valid_predecessor_v1"
    supported_provider_name: str = "confirmed_extrema_pair"
    supported_provider_version: str = "v1"
    required_anchor_count: int = 2
    grouping_key: tuple[str, ...] = ("role", "second_anchor_id")
    primary_order: str = "maximum_first_anchor_pivot_time"
    tie_break_order: tuple[str, ...] = ("first_anchor_id", "candidate_id")
    output_cardinality: str = "one_per_nonempty_group"

    def __post_init__(self) -> None:
        exact_strings = {
            "policy_name": "latest_valid_predecessor",
            "policy_version": "v1",
            "research_family_id": "latest_valid_predecessor_v1",
            "supported_provider_name": "confirmed_extrema_pair",
            "supported_provider_version": "v1",
            "primary_order": "maximum_first_anchor_pivot_time",
            "output_cardinality": "one_per_nonempty_group",
        }
        for field_name, expected in exact_strings.items():
            value = require_string(getattr(self, field_name), field_name=f"policy.{field_name}")
            if value != expected:
                raise ContractValidationError(f"policy.{field_name} is immutable")
            object.__setattr__(self, field_name, value)
        if require_integer(self.required_anchor_count, field_name="policy.required_anchor_count") != 2:
            raise ContractValidationError("policy.required_anchor_count must be 2")
        if not isinstance(self.grouping_key, tuple) or self.grouping_key != (
            "role",
            "second_anchor_id",
        ):
            raise ContractValidationError("policy.grouping_key is immutable")
        if not isinstance(self.tie_break_order, tuple) or self.tie_break_order != (
            "first_anchor_id",
            "candidate_id",
        ):
            raise ContractValidationError("policy.tie_break_order is immutable")
        object.__setattr__(self, "required_anchor_count", 2)
        object.__setattr__(self, "grouping_key", ("role", "second_anchor_id"))
        object.__setattr__(self, "tie_break_order", ("first_anchor_id", "candidate_id"))

    @property
    def supported_provider_identity(self) -> str:
        return provider_identity(self.supported_provider_name, self.supported_provider_version)

    @property
    def policy_identity(self) -> str:
        return deterministic_hash(POLICY_IDENTITY_NAMESPACE, self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "policy_version": self.policy_version,
            "research_family_id": self.research_family_id,
            "supported_provider": {
                "name": self.supported_provider_name,
                "version": self.supported_provider_version,
            },
            "required_anchor_count": self.required_anchor_count,
            "grouping_key": list(self.grouping_key),
            "primary_order": self.primary_order,
            "tie_break_order": list(self.tie_break_order),
            "output_cardinality": self.output_cardinality,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LatestValidPredecessorPolicy":
        if not isinstance(value, Mapping):
            raise ContractValidationError("selection policy payload must be a mapping")
        expected = {
            "policy_name",
            "policy_version",
            "research_family_id",
            "supported_provider",
            "required_anchor_count",
            "grouping_key",
            "primary_order",
            "tie_break_order",
            "output_cardinality",
        }
        if set(value) != expected or not isinstance(value["supported_provider"], Mapping):
            raise ContractValidationError("selection policy payload keys mismatch")
        provider = value["supported_provider"]
        if set(provider) != {"name", "version"}:
            raise ContractValidationError("selection policy provider keys mismatch")
        if not isinstance(value["grouping_key"], list) or not isinstance(
            value["tie_break_order"], list
        ):
            raise ContractValidationError("selection policy ordering fields must be lists")
        return cls(
            policy_name=value["policy_name"],
            policy_version=value["policy_version"],
            research_family_id=value["research_family_id"],
            supported_provider_name=provider["name"],
            supported_provider_version=provider["version"],
            required_anchor_count=value["required_anchor_count"],
            grouping_key=tuple(value["grouping_key"]),
            primary_order=value["primary_order"],
            tie_break_order=tuple(value["tie_break_order"]),
            output_cardinality=value["output_cardinality"],
        )


@dataclass(frozen=True, slots=True)
class CandidateSelectionDecision:
    """One deterministic decision for one role/second-anchor group."""

    role: LineRole | str
    second_anchor_id: str
    second_anchor_time: datetime
    considered_candidate_ids: tuple[str, ...]
    selected_candidate_id: str
    selected_first_anchor_id: str
    selected_first_anchor_time: datetime
    latest_timestamp_tie_count: int
    selection_policy_identity: str
    decision_id: str

    def __post_init__(self) -> None:
        try:
            role = LineRole(self.role)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(f"invalid decision role: {self.role!r}") from exc
        second_anchor_id = require_hash(self.second_anchor_id, field_name="decision.second_anchor_id")
        second_anchor_time = require_utc(
            self.second_anchor_time, field_name="decision.second_anchor_time"
        )
        first_anchor_time = require_utc(
            self.selected_first_anchor_time,
            field_name="decision.selected_first_anchor_time",
        )
        if not isinstance(self.considered_candidate_ids, tuple) or not self.considered_candidate_ids:
            raise ContractValidationError("decision considered IDs must be a non-empty tuple")
        considered = tuple(
            require_hash(candidate_id, field_name="decision.considered_candidate_id")
            for candidate_id in self.considered_candidate_ids
        )
        if len(set(considered)) != len(considered):
            raise ContractValidationError("decision considered IDs must be unique")
        if considered != tuple(sorted(considered)):
            raise ContractValidationError("decision considered IDs must be sorted")
        selected = require_hash(
            self.selected_candidate_id, field_name="decision.selected_candidate_id"
        )
        if selected not in considered:
            raise ContractValidationError("selected candidate must be considered")
        first_anchor_id = require_hash(
            self.selected_first_anchor_id,
            field_name="decision.selected_first_anchor_id",
        )
        tie_count = require_integer(
            self.latest_timestamp_tie_count,
            field_name="decision.latest_timestamp_tie_count",
            minimum=1,
        )
        if tie_count > len(considered):
            raise ContractValidationError("decision tie count exceeds considered candidates")
        policy_identity = require_hash(
            self.selection_policy_identity,
            field_name="decision.selection_policy_identity",
        )
        decision_id = require_hash(self.decision_id, field_name="decision.decision_id")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "second_anchor_id", second_anchor_id)
        object.__setattr__(self, "second_anchor_time", second_anchor_time)
        object.__setattr__(self, "considered_candidate_ids", considered)
        object.__setattr__(self, "selected_candidate_id", selected)
        object.__setattr__(self, "selected_first_anchor_id", first_anchor_id)
        object.__setattr__(self, "selected_first_anchor_time", first_anchor_time)
        object.__setattr__(self, "latest_timestamp_tie_count", tie_count)
        object.__setattr__(self, "selection_policy_identity", policy_identity)
        object.__setattr__(self, "decision_id", decision_id)
        if self.expected_decision_id != decision_id:
            raise ContractValidationError("decision_id does not match canonical content")

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "second_anchor_id": self.second_anchor_id,
            "second_anchor_time": self.second_anchor_time,
            "considered_candidate_ids": list(self.considered_candidate_ids),
            "selected_candidate_id": self.selected_candidate_id,
            "selected_first_anchor_id": self.selected_first_anchor_id,
            "selected_first_anchor_time": self.selected_first_anchor_time,
            "latest_timestamp_tie_count": self.latest_timestamp_tie_count,
            "selection_policy_identity": self.selection_policy_identity,
        }

    @property
    def expected_decision_id(self) -> str:
        return deterministic_hash(DECISION_IDENTITY_NAMESPACE, self._identity_payload())

    @classmethod
    def create(
        cls,
        *,
        role: LineRole | str,
        second_anchor_id: str,
        second_anchor_time: datetime,
        considered_candidate_ids: tuple[str, ...],
        selected_candidate_id: str,
        selected_first_anchor_id: str,
        selected_first_anchor_time: datetime,
        latest_timestamp_tie_count: int,
        selection_policy_identity: str,
    ) -> "CandidateSelectionDecision":
        """Build a decision with its content-derived identity."""

        role_value = LineRole(role).value
        payload = {
            "role": role_value,
            "second_anchor_id": second_anchor_id,
            "second_anchor_time": second_anchor_time,
            "considered_candidate_ids": list(considered_candidate_ids),
            "selected_candidate_id": selected_candidate_id,
            "selected_first_anchor_id": selected_first_anchor_id,
            "selected_first_anchor_time": selected_first_anchor_time,
            "latest_timestamp_tie_count": latest_timestamp_tie_count,
            "selection_policy_identity": selection_policy_identity,
        }
        return cls(
            role=role,
            second_anchor_id=second_anchor_id,
            second_anchor_time=second_anchor_time,
            considered_candidate_ids=considered_candidate_ids,
            selected_candidate_id=selected_candidate_id,
            selected_first_anchor_id=selected_first_anchor_id,
            selected_first_anchor_time=selected_first_anchor_time,
            latest_timestamp_tie_count=latest_timestamp_tie_count,
            selection_policy_identity=selection_policy_identity,
            decision_id=deterministic_hash(DECISION_IDENTITY_NAMESPACE, payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"decision_id": self.decision_id, **primitive(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CandidateSelectionDecision":
        if not isinstance(value, Mapping):
            raise ContractValidationError("selection decision payload must be a mapping")
        expected = {
            "role",
            "second_anchor_id",
            "second_anchor_time",
            "considered_candidate_ids",
            "selected_candidate_id",
            "selected_first_anchor_id",
            "selected_first_anchor_time",
            "latest_timestamp_tie_count",
            "selection_policy_identity",
            "decision_id",
        }
        if set(value) != expected or not isinstance(value["considered_candidate_ids"], list):
            raise ContractValidationError("selection decision payload keys mismatch")
        try:
            return cls(
                role=value["role"],
                second_anchor_id=value["second_anchor_id"],
                second_anchor_time=parse_utc_isoformat(
                    value["second_anchor_time"], field_name="decision.second_anchor_time"
                ),
                considered_candidate_ids=tuple(value["considered_candidate_ids"]),
                selected_candidate_id=value["selected_candidate_id"],
                selected_first_anchor_id=value["selected_first_anchor_id"],
                selected_first_anchor_time=parse_utc_isoformat(
                    value["selected_first_anchor_time"],
                    field_name="decision.selected_first_anchor_time",
                ),
                latest_timestamp_tie_count=value["latest_timestamp_tie_count"],
                selection_policy_identity=value["selection_policy_identity"],
                decision_id=value["decision_id"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid selection decision payload") from exc


@dataclass(frozen=True, slots=True)
class SelectionDiagnostics:
    """Selection accounting with no research-only metrics."""

    source_candidate_count: int
    source_group_count: int
    selected_candidate_count: int
    rejected_candidate_count: int
    support_selected_count: int
    resistance_selected_count: int
    latest_timestamp_tie_group_count: int

    def __post_init__(self) -> None:
        values = {}
        for field_name in (
            "source_candidate_count",
            "source_group_count",
            "selected_candidate_count",
            "rejected_candidate_count",
            "support_selected_count",
            "resistance_selected_count",
            "latest_timestamp_tie_group_count",
        ):
            values[field_name] = require_integer(
                getattr(self, field_name), field_name=f"diagnostics.{field_name}"
            )
        if values["source_group_count"] > values["source_candidate_count"]:
            raise ContractValidationError("diagnostic group count exceeds source count")
        if values["selected_candidate_count"] != values["source_group_count"]:
            raise ContractValidationError("diagnostic selected/group count mismatch")
        if values["rejected_candidate_count"] != (
            values["source_candidate_count"] - values["selected_candidate_count"]
        ):
            raise ContractValidationError("diagnostic rejected count mismatch")
        if values["support_selected_count"] + values["resistance_selected_count"] != values[
            "selected_candidate_count"
        ]:
            raise ContractValidationError("diagnostic role counts mismatch")
        if values["latest_timestamp_tie_group_count"] > values["source_group_count"]:
            raise ContractValidationError("diagnostic tie count exceeds group count")
        for field_name, value in values.items():
            object.__setattr__(self, field_name, value)

    def to_dict(self) -> dict[str, Any]:
        return primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SelectionDiagnostics":
        if not isinstance(value, Mapping):
            raise ContractValidationError("selection diagnostics payload must be a mapping")
        expected = {
            "source_candidate_count",
            "source_group_count",
            "selected_candidate_count",
            "rejected_candidate_count",
            "support_selected_count",
            "resistance_selected_count",
            "latest_timestamp_tie_group_count",
        }
        if set(value) != expected:
            raise ContractValidationError("selection diagnostics payload keys mismatch")
        try:
            return cls(**dict(value))
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid selection diagnostics payload") from exc


@dataclass(frozen=True, slots=True)
class CandidateSelectionSnapshot:
    """Immutable, content-addressed output of the explicit selection layer."""

    asset: str
    timeframe: str
    observed_at: datetime
    source_snapshot_id: str
    input_identity: str
    discovery_config_identity: str
    provider_identity: str
    selection_policy_identity: str
    status: SelectionStatus | str
    source_reason: AbstentionReason | str | None
    source_candidate_set_identity: str
    selected_candidates: tuple[LineCandidate, ...]
    decisions: tuple[CandidateSelectionDecision, ...]
    diagnostics: SelectionDiagnostics

    def __post_init__(self) -> None:
        asset = require_string(self.asset, field_name="selection.asset")
        timeframe = require_string(self.timeframe, field_name="selection.timeframe")
        observed = require_utc(self.observed_at, field_name="selection.observed_at")
        source_snapshot_id = require_hash(
            self.source_snapshot_id, field_name="selection.source_snapshot_id"
        )
        input_identity = require_hash(self.input_identity, field_name="selection.input_identity")
        config_identity = require_hash(
            self.discovery_config_identity,
            field_name="selection.discovery_config_identity",
        )
        provider_identity_value = require_hash(
            self.provider_identity, field_name="selection.provider_identity"
        )
        policy_identity = require_hash(
            self.selection_policy_identity,
            field_name="selection.selection_policy_identity",
        )
        try:
            status = SelectionStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("invalid selection status") from exc
        reason = None
        if self.source_reason is not None:
            try:
                reason = AbstentionReason(self.source_reason)
            except (TypeError, ValueError) as exc:
                raise ContractValidationError("invalid selection source reason") from exc
        source_set_identity = require_hash(
            self.source_candidate_set_identity,
            field_name="selection.source_candidate_set_identity",
        )
        if not isinstance(self.selected_candidates, tuple):
            raise ContractValidationError("selected candidates must be a tuple")
        if not isinstance(self.decisions, tuple):
            raise ContractValidationError("selection decisions must be a tuple")
        if not isinstance(self.diagnostics, SelectionDiagnostics):
            raise ContractValidationError("selection diagnostics must be SelectionDiagnostics")
        selected_candidates = self.selected_candidates
        decisions = self.decisions
        if any(not isinstance(candidate, LineCandidate) for candidate in selected_candidates):
            raise ContractValidationError("selected candidates must be LineCandidate values")
        if any(not isinstance(decision, CandidateSelectionDecision) for decision in decisions):
            raise ContractValidationError("selection decisions must be decision values")
        decision_group_keys = tuple(
            (decision.role, decision.second_anchor_id)
            for decision in decisions
        )
        if len(set(decision_group_keys)) != len(decision_group_keys):
            raise ContractValidationError(
                "selection decisions must have unique role/second-anchor groups"
            )
        if self.diagnostics.source_group_count != len(decision_group_keys):
            raise ContractValidationError(
                "diagnostic source-group count does not match decisions"
            )
        if any(
            decision.selection_policy_identity != policy_identity
            for decision in decisions
        ):
            raise ContractValidationError(
                "decision policy identity does not match selection snapshot"
            )
        expected_tie_group_count = sum(
            decision.latest_timestamp_tie_count > 1
            for decision in decisions
        )
        if self.diagnostics.latest_timestamp_tie_group_count != expected_tie_group_count:
            raise ContractValidationError(
                "diagnostic tie-group count does not match decisions"
            )
        candidate_ids = tuple(candidate.candidate_id for candidate in selected_candidates)
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ContractValidationError("selected candidate IDs must be unique")
        if any(
            candidate.asset != asset
            or candidate.timeframe != timeframe
            or candidate.observed_at != observed
            or provider_identity(candidate.provider_name, candidate.provider_version)
            != provider_identity_value
            or len(candidate.anchors) != 2
            for candidate in selected_candidates
        ):
            raise ContractValidationError("selected candidate binding or anchor count mismatch")
        for candidate in selected_candidates:
            for anchor in candidate.anchors:
                require_hash(anchor.anchor_id, field_name="selection.anchor_id")
        decision_ids = tuple(decision.selected_candidate_id for decision in decisions)
        if len(set(decision_ids)) != len(decision_ids):
            raise ContractValidationError("decision selected IDs must be unique")
        selected_order = tuple(
            sorted(
                selected_candidates,
                key=lambda item: (
                    item.role.value,
                    item.anchors[1].pivot_time,
                    item.anchors[1].anchor_id,
                    item.candidate_id,
                ),
            )
        )
        if selected_order != selected_candidates:
            raise ContractValidationError("selected candidates must use canonical ordering")
        if tuple(candidate.candidate_id for candidate in selected_order) != decision_ids:
            raise ContractValidationError("decisions must use selected-candidate ordering")
        if status is SelectionStatus.SELECTED:
            if reason is not None or not selected_candidates or not decisions:
                raise ContractValidationError("selected snapshot requires candidates and decisions")
            considered_groups: list[str] = []
            for decision, candidate in zip(decisions, selected_candidates):
                if decision.role is not candidate.role:
                    raise ContractValidationError("decision role does not match candidate")
                second_anchor = candidate.anchors[1]
                first_anchor = candidate.anchors[0]
                if (
                    decision.second_anchor_id != second_anchor.anchor_id
                    or decision.second_anchor_time != second_anchor.pivot_time
                    or decision.selected_first_anchor_id != first_anchor.anchor_id
                    or decision.selected_first_anchor_time != first_anchor.pivot_time
                ):
                    raise ContractValidationError("decision anchor fields do not match candidate")
                considered_groups.extend(decision.considered_candidate_ids)
            if len(set(considered_groups)) != len(considered_groups):
                raise ContractValidationError("decision considered IDs must form a disjoint partition")
            if len(considered_groups) != self.diagnostics.source_candidate_count:
                raise ContractValidationError("decision partition/source count mismatch")
            if candidate_set_identity(tuple(considered_groups)) != source_set_identity:
                raise ContractValidationError("source candidate set identity mismatch")
            if set(decision_ids) != set(candidate_ids):
                raise ContractValidationError("decision selected IDs do not match candidates")
            if self.diagnostics.source_candidate_count <= 0:
                raise ContractValidationError("selected snapshot requires source candidates")
            if self.diagnostics.selected_candidate_count != len(selected_candidates):
                raise ContractValidationError("selected diagnostic count mismatch")
            support_count = sum(candidate.role is LineRole.SUPPORT for candidate in selected_candidates)
            resistance_count = sum(
                candidate.role is LineRole.RESISTANCE for candidate in selected_candidates
            )
            if (
                self.diagnostics.support_selected_count != support_count
                or self.diagnostics.resistance_selected_count != resistance_count
            ):
                raise ContractValidationError("selected diagnostic role count mismatch")
        else:
            if selected_candidates or decisions or reason is None:
                raise ContractValidationError("source outcome snapshot must be empty and reasoned")
            if (
                status is SelectionStatus.SOURCE_FAILED
                and reason is not AbstentionReason.PROVIDER_FAILURE
            ) or (
                status is SelectionStatus.SOURCE_ABSTAINED
                and reason is AbstentionReason.PROVIDER_FAILURE
            ):
                raise ContractValidationError("selection source status/reason combination is invalid")
            if self.diagnostics != SelectionDiagnostics(0, 0, 0, 0, 0, 0, 0):
                raise ContractValidationError("source outcome diagnostics must be zero")
            if source_set_identity != candidate_set_identity(()) :
                raise ContractValidationError("empty source candidate set identity mismatch")
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "source_snapshot_id", source_snapshot_id)
        object.__setattr__(self, "input_identity", input_identity)
        object.__setattr__(self, "discovery_config_identity", config_identity)
        object.__setattr__(self, "provider_identity", provider_identity_value)
        object.__setattr__(self, "selection_policy_identity", policy_identity)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "source_reason", reason)
        object.__setattr__(self, "source_candidate_set_identity", source_set_identity)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "observed_at": self.observed_at,
            "source_snapshot_id": self.source_snapshot_id,
            "input_identity": self.input_identity,
            "discovery_config_identity": self.discovery_config_identity,
            "provider_identity": self.provider_identity,
            "selection_policy_identity": self.selection_policy_identity,
            "status": self.status.value,
            "source_reason": self.source_reason.value if self.source_reason is not None else None,
            "source_candidate_set_identity": self.source_candidate_set_identity,
            "selected_candidates": [candidate.to_dict() for candidate in self.selected_candidates],
            "decisions": [decision.to_dict() for decision in self.decisions],
            "diagnostics": self.diagnostics.to_dict(),
        }

    @property
    def snapshot_id(self) -> str:
        return deterministic_hash(SNAPSHOT_IDENTITY_NAMESPACE, self._identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id, **primitive(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CandidateSelectionSnapshot":
        if not isinstance(value, Mapping):
            raise ContractValidationError("selection snapshot payload must be a mapping")
        expected = {
            "snapshot_id",
            "asset",
            "timeframe",
            "observed_at",
            "source_snapshot_id",
            "input_identity",
            "discovery_config_identity",
            "provider_identity",
            "selection_policy_identity",
            "status",
            "source_reason",
            "source_candidate_set_identity",
            "selected_candidates",
            "decisions",
            "diagnostics",
        }
        if set(value) != expected:
            raise ContractValidationError("selection snapshot payload keys mismatch")
        if not isinstance(value["selected_candidates"], list) or not isinstance(
            value["decisions"], list
        ):
            raise ContractValidationError("selection snapshot collections must be lists")
        try:
            result = cls(
                asset=value["asset"],
                timeframe=value["timeframe"],
                observed_at=parse_utc_isoformat(value["observed_at"], field_name="selection.observed_at"),
                source_snapshot_id=value["source_snapshot_id"],
                input_identity=value["input_identity"],
                discovery_config_identity=value["discovery_config_identity"],
                provider_identity=value["provider_identity"],
                selection_policy_identity=value["selection_policy_identity"],
                status=value["status"],
                source_reason=value["source_reason"],
                source_candidate_set_identity=value["source_candidate_set_identity"],
                selected_candidates=tuple(
                    LineCandidate.from_dict(item) for item in value["selected_candidates"]
                ),
                decisions=tuple(
                    CandidateSelectionDecision.from_dict(item) for item in value["decisions"]
                ),
                diagnostics=SelectionDiagnostics.from_dict(value["diagnostics"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid selection snapshot payload") from exc
        if value["snapshot_id"] != result.snapshot_id:
            raise ContractValidationError("selection snapshot_id does not match canonical content")
        return result


__all__ = [
    "CANDIDATE_SET_IDENTITY_NAMESPACE",
    "CandidateSelectionDecision",
    "CandidateSelectionSnapshot",
    "DECISION_IDENTITY_NAMESPACE",
    "LatestValidPredecessorPolicy",
    "POLICY_IDENTITY_NAMESPACE",
    "SelectionDiagnostics",
    "SelectionStatus",
    "SNAPSHOT_IDENTITY_NAMESPACE",
    "candidate_set_identity",
]
