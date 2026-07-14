"""Deterministic in-memory snapshot repository for Phase A."""

from __future__ import annotations

import json
import math
from typing import Protocol

from .contracts import (
    ContractValidationError,
    FamilyLifecycleState,
    FamilySourceGroupAudit,
    FamilyTransition,
    FamilyTransitionType,
    TrendlineFamilyState,
    TrendlineFamilySnapshot,
    canonical_json,
    trendline_family_snapshot_has_phase_g_evidence,
    validate_trendline_family_snapshot_identity,
)


class SnapshotVersionError(ContractValidationError):
    """Raised when an update would fork or regress a snapshot lineage."""


class TrendlineFamilyRepository(Protocol):
    def latest_snapshot(self, asset: str, timeframe: str) -> TrendlineFamilySnapshot | None: ...

    def save_snapshot(self, snapshot: TrendlineFamilySnapshot) -> None: ...


def serialize_snapshot(snapshot: TrendlineFamilySnapshot) -> str:
    return canonical_json(snapshot.to_dict())


def deserialize_snapshot(payload: str) -> TrendlineFamilySnapshot:
    if not isinstance(payload, str):
        raise ContractValidationError("snapshot payload must be a JSON string")
    try:
        value = json.loads(payload)
        return TrendlineFamilySnapshot.from_dict(value)
    except ContractValidationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ContractValidationError("snapshot payload is not valid JSON") from exc


class InMemoryTrendlineFamilyRepository:
    """Snapshot store with explicit previous-snapshot and family-version checks."""

    def __init__(self) -> None:
        self._snapshots: dict[tuple[str, str], TrendlineFamilySnapshot] = {}

    def latest_snapshot(self, asset: str, timeframe: str) -> TrendlineFamilySnapshot | None:
        snapshot = self._snapshots.get((asset, timeframe))
        return None if snapshot is None else deserialize_snapshot(serialize_snapshot(snapshot))

    def save_snapshot(self, snapshot: TrendlineFamilySnapshot) -> None:
        key = (snapshot.asset, snapshot.timeframe)
        previous = self._snapshots.get(key)
        self._validate_lineage(snapshot, previous)
        self._snapshots[key] = deserialize_snapshot(serialize_snapshot(snapshot))

    @staticmethod
    def _validate_lineage(
        snapshot: TrendlineFamilySnapshot,
        previous: TrendlineFamilySnapshot | None,
    ) -> None:
        try:
            validate_trendline_family_snapshot_identity(snapshot)
        except ContractValidationError as exc:
            raise SnapshotVersionError(str(exc)) from exc
        new_families = {
            family.family_id: family
            for family in snapshot.active_families + snapshot.dormant_families
        }
        if previous is None:
            if snapshot.previous_snapshot_id is not None:
                raise SnapshotVersionError("first snapshot must not declare a previous snapshot")
            for family_id, family in new_families.items():
                if family.version != 1:
                    raise SnapshotVersionError(f"new family {family_id} must start at version one")
            if _phase_g_enabled(snapshot):
                _validate_phase_g_transition_lineage(
                    snapshot=snapshot,
                    previous_families={},
                    current_families=new_families,
                )
            return
        if snapshot.previous_snapshot_id != previous.snapshot_id:
            raise SnapshotVersionError("snapshot previous_snapshot_id does not match repository head")
        if snapshot.snapshot_id == previous.snapshot_id:
            raise SnapshotVersionError("snapshot ID must advance")
        if snapshot.timestamp <= previous.timestamp:
            raise SnapshotVersionError("snapshot timestamp must advance")
        old_families = {family.family_id: family for family in previous.active_families + previous.dormant_families}
        for family_id in old_families.keys() & new_families.keys():
            if new_families[family_id].version != old_families[family_id].version + 1:
                raise SnapshotVersionError(f"family {family_id} version must advance by one")
        for family_id in new_families.keys() - old_families.keys():
            if new_families[family_id].version != 1:
                raise SnapshotVersionError(f"new family {family_id} must start at version one")
        previous_phase_g = _phase_g_enabled(previous)
        current_phase_g = _phase_g_enabled(snapshot)
        if previous_phase_g and not current_phase_g:
            raise SnapshotVersionError("Phase-G repository lineage cannot downgrade to legacy diagnostics")
        if previous_phase_g or current_phase_g:
            _validate_phase_g_transition_lineage(
                snapshot=snapshot,
                previous_families=old_families,
                current_families=new_families,
            )


def _phase_g_enabled(snapshot: TrendlineFamilySnapshot) -> bool:
    return trendline_family_snapshot_has_phase_g_evidence(snapshot)


def _validate_phase_g_transition_lineage(
    *,
    snapshot: TrendlineFamilySnapshot,
    previous_families: dict[str, TrendlineFamilyState],
    current_families: dict[str, TrendlineFamilyState],
) -> None:
    """Bind Phase-G membership evidence to both sides of repository lineage."""

    transitions_by_family_id: dict[str, FamilyTransition] = {}
    for transition in snapshot.transitions:
        if transition.family_id in transitions_by_family_id:
            raise SnapshotVersionError("Phase-G repository lineage requires one transition per family")
        transitions_by_family_id[transition.family_id] = transition

    expected_transition_family_ids = set(previous_families) | set(current_families)
    if set(transitions_by_family_id) != expected_transition_family_ids:
        raise SnapshotVersionError("Phase-G repository lineage requires complete family transition coverage")

    for family_id in sorted(expected_transition_family_ids):
        previous = previous_families.get(family_id)
        current = current_families.get(family_id)
        transition = transitions_by_family_id[family_id]
        _validate_phase_g_transition(
            snapshot=snapshot,
            transition=transition,
            previous=previous,
            current=current,
        )


def _validate_phase_g_transition(
    *,
    snapshot: TrendlineFamilySnapshot,
    transition: FamilyTransition,
    previous: TrendlineFamilyState | None,
    current: TrendlineFamilyState | None,
) -> None:
    if transition.timestamp != snapshot.timestamp:
        raise SnapshotVersionError("Phase-G transition timestamp must match snapshot timestamp")
    previous_member_ids = set() if previous is None else {member.member_id for member in previous.members}
    current_member_ids = set() if current is None else {member.member_id for member in current.members}
    expected_added = current_member_ids - previous_member_ids
    expected_continued = current_member_ids & previous_member_ids
    expected_removed = previous_member_ids - current_member_ids

    _validate_transition_type(previous=previous, current=current, transition=transition)

    if set(transition.added_member_ids) != expected_added:
        raise SnapshotVersionError("Phase-G transition added_member_ids do not match repository lineage")
    if set(transition.continued_member_ids) != expected_continued:
        raise SnapshotVersionError("Phase-G transition continued_member_ids do not match repository lineage")
    if set(transition.removed_member_ids) != expected_removed:
        raise SnapshotVersionError("Phase-G transition removed_member_ids do not match repository lineage")
    if transition.previous_rail_count != len(previous_member_ids):
        raise SnapshotVersionError("Phase-G transition previous_rail_count does not match repository lineage")
    if transition.current_rail_count != len(current_member_ids):
        raise SnapshotVersionError("Phase-G transition current_rail_count does not match repository lineage")

    expected_previous_representative = None if previous is None else previous.representative_member_id
    expected_current_representative = None if current is None else current.representative_member_id
    if transition.previous_representative_member_id != expected_previous_representative:
        raise SnapshotVersionError("Phase-G transition previous representative does not match repository lineage")
    if transition.current_representative_member_id != expected_current_representative:
        raise SnapshotVersionError("Phase-G transition current representative does not match repository lineage")
    if transition.representative_changed is not (
        expected_previous_representative is not None
        and expected_current_representative is not None
        and expected_previous_representative != expected_current_representative
    ):
        raise SnapshotVersionError("Phase-G transition representative_changed does not match repository lineage")

    if transition.transition_type is FamilyTransitionType.ROLE_REVERSED:
        _validate_role_reversal_identity(previous=previous, current=current, transition=transition)

    _validate_matched_candidate_audit(
        snapshot=snapshot,
        transition=transition,
        current=current,
        source_groups={
            audit.source_group_id: audit for audit in snapshot.source_group_audits
        },
    )


def _validate_transition_type(
    *,
    previous: TrendlineFamilyState | None,
    current: TrendlineFamilyState | None,
    transition: FamilyTransition,
) -> None:
    if previous is None:
        if current is None or transition.transition_type is not FamilyTransitionType.BIRTH:
            raise SnapshotVersionError("new Phase-G family requires a BIRTH transition")
        return
    if current is None:
        if transition.transition_type is not FamilyTransitionType.EXPIRE:
            raise SnapshotVersionError("removed Phase-G family requires an EXPIRE transition")
        return
    if previous.current_role is not current.current_role:
        if transition.transition_type is not FamilyTransitionType.ROLE_REVERSED:
            raise SnapshotVersionError("Phase-G role change requires ROLE_REVERSED transition")
        return
    if transition.transition_type is FamilyTransitionType.ROLE_REVERSED:
        raise SnapshotVersionError("ROLE_REVERSED transition requires a family role change")
    if (
        previous.lifecycle_state is FamilyLifecycleState.DORMANT
        and current.lifecycle_state is FamilyLifecycleState.ACTIVE
    ):
        if transition.transition_type is not FamilyTransitionType.REACTIVATE:
            raise SnapshotVersionError("DORMANT to ACTIVE transition requires REACTIVATE")
        return
    if (
        previous.lifecycle_state is FamilyLifecycleState.ACTIVE
        and current.lifecycle_state is FamilyLifecycleState.DORMANT
    ):
        if transition.transition_type is not FamilyTransitionType.DORMANT:
            raise SnapshotVersionError("ACTIVE to DORMANT transition requires DORMANT")
        return
    if (
        previous.lifecycle_state is FamilyLifecycleState.DORMANT
        and current.lifecycle_state is FamilyLifecycleState.DORMANT
    ):
        if transition.transition_type is not FamilyTransitionType.WEAKEN:
            raise SnapshotVersionError("DORMANT to DORMANT transition requires WEAKEN")
        return
    if (
        previous.lifecycle_state is not FamilyLifecycleState.ACTIVE
        or current.lifecycle_state is not FamilyLifecycleState.ACTIVE
    ):
        raise SnapshotVersionError("Phase-G transition has unsupported lifecycle evolution")
    if transition.association_score is None:
        if transition.transition_type is not FamilyTransitionType.WEAKEN:
            raise SnapshotVersionError("unmatched ACTIVE transition requires WEAKEN")
        return
    confidence_delta = current.confidence - previous.confidence
    if math.isclose(confidence_delta, 0.0, rel_tol=1e-12, abs_tol=1e-12):
        expected = FamilyTransitionType.CONTINUE
    elif confidence_delta > 0.0:
        expected = FamilyTransitionType.STRENGTHEN
    else:
        expected = FamilyTransitionType.WEAKEN
    if transition.transition_type is not expected:
        raise SnapshotVersionError(
            f"matched ACTIVE transition requires {expected.value} from confidence evolution"
        )


def _validate_role_reversal_identity(
    *,
    previous: TrendlineFamilyState | None,
    current: TrendlineFamilyState | None,
    transition: FamilyTransition,
) -> None:
    if previous is None or current is None:
        raise SnapshotVersionError("ROLE_REVERSED transition requires previous and current family state")
    if transition.added_member_ids or transition.removed_member_ids:
        raise SnapshotVersionError("ROLE_REVERSED transition cannot add or remove rails")
    if set(transition.continued_member_ids) != {member.member_id for member in previous.members}:
        raise SnapshotVersionError("ROLE_REVERSED transition must continue every prior rail")
    if previous.representative_member_id != current.representative_member_id:
        raise SnapshotVersionError("ROLE_REVERSED transition must preserve its representative member")
    if previous.current_role is current.current_role:
        raise SnapshotVersionError("ROLE_REVERSED transition must change family role")
    previous_members = {member.member_id: member for member in previous.members}
    current_members = {member.member_id: member for member in current.members}
    if set(previous_members) != set(current_members):
        raise SnapshotVersionError("ROLE_REVERSED transition must preserve member IDs")
    for member_id, previous_member in previous_members.items():
        current_member = current_members[member_id]
        if (
            previous_member.candidate_id != current_member.candidate_id
            or previous_member.geometry != current_member.geometry
            or previous_member.anchors != current_member.anchors
            or current_member.role is not current.current_role
        ):
            raise SnapshotVersionError("ROLE_REVERSED transition must preserve exact rail geometry and anchors")


def _validate_matched_candidate_audit(
    *,
    snapshot: TrendlineFamilySnapshot,
    transition: FamilyTransition,
    current: TrendlineFamilyState | None,
    source_groups: dict[str, FamilySourceGroupAudit],
) -> None:
    if transition.transition_type is FamilyTransitionType.EXPIRE:
        if (
            transition.matched_candidate_ids
            or transition.source_group_id is not None
            or transition.source_group_candidate_ids
        ):
            raise SnapshotVersionError("EXPIRE transition cannot retain matched candidate evidence")
        return
    if current is None:  # Defensive narrowing after transition coverage checks.
        raise SnapshotVersionError("published Phase-G transition requires a current family")

    current_candidate_ids = tuple(sorted(member.candidate_id for member in current.members))
    if transition.transition_type in {
        FamilyTransitionType.BIRTH,
        FamilyTransitionType.ROLE_REVERSED,
    }:
        if transition.matched_candidate_ids != current_candidate_ids:
            raise SnapshotVersionError("Phase-G transition matched candidates must equal current rails")
    else:
        if transition.association_score is None:
            if (
                transition.matched_candidate_ids
                or transition.source_group_id is not None
                or transition.source_group_candidate_ids
            ):
                raise SnapshotVersionError("unmatched lifecycle transition cannot retain matched candidate evidence")
            return
        if transition.matched_candidate_ids != current_candidate_ids:
            raise SnapshotVersionError("matched transition candidates must equal current rails")

    if transition.source_group_candidate_ids:
        if transition.source_group_id is None:
            raise SnapshotVersionError("matched candidate audit requires source-group evidence")
        source_group = source_groups.get(transition.source_group_id)
        if source_group is None:
            raise SnapshotVersionError("matched candidate audit source-group record is missing")
        if (
            source_group.asset != snapshot.asset
            or source_group.timeframe != snapshot.timeframe
            or source_group.role is not current.current_role
            or source_group.observed_at != snapshot.timestamp
            or source_group.model_version != snapshot.model_version
            or source_group.config_version != snapshot.config_version
            or source_group.resolved_config_hash != snapshot.resolved_config_hash
            or source_group.candidate_ids != transition.source_group_candidate_ids
        ):
            raise SnapshotVersionError("matched candidate audit source-group record is inconsistent")
        if (
            transition.transition_type is not FamilyTransitionType.ROLE_REVERSED
            and transition.source_group_candidate_ids != transition.matched_candidate_ids
        ):
            raise SnapshotVersionError("matched transition source-group candidates must equal current rails")
    elif transition.source_group_id is not None:
        raise SnapshotVersionError("empty matched candidate audit cannot declare source_group_id")
