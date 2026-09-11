"""Pure exact-structure tracking update."""

from __future__ import annotations

from typing import Any

from ..domain.validation import ContractValidationError
from ..selection import CandidateSelectionSnapshot, SelectionStatus
from .contracts import (
    ExactSelectedStructureTrackingPolicy,
    FamilyTrackingTransition,
    FamilyTrackingTransitionType,
    TrackedTrendlineFamily,
    TrackingDiagnostics,
    TrackingStatus,
    TrendlineTrackingSnapshot,
    tracked_family_id,
)


def _validate_previous_binding(
    selection: CandidateSelectionSnapshot,
    previous: TrendlineTrackingSnapshot | None,
    policy: ExactSelectedStructureTrackingPolicy,
) -> None:
    if not isinstance(selection, CandidateSelectionSnapshot):
        raise ContractValidationError("tracking selection must be CandidateSelectionSnapshot")
    if not isinstance(policy, ExactSelectedStructureTrackingPolicy):
        raise ContractValidationError(
            "tracking policy must be ExactSelectedStructureTrackingPolicy"
        )
    if selection.selection_policy_identity != policy.supported_selection_policy_identity:
        raise ContractValidationError("selection policy identity is unsupported by tracking policy")
    if previous is None:
        return
    if not isinstance(previous, TrendlineTrackingSnapshot):
        raise ContractValidationError(
            "tracking previous must be TrendlineTrackingSnapshot or None"
        )
    if selection.asset != previous.asset or selection.timeframe != previous.timeframe:
        raise ContractValidationError("tracking asset/timeframe drift")
    # ProviderInput identity is a point-in-time value and must advance with the stream.
    if selection.discovery_config_identity != previous.discovery_config_identity:
        raise ContractValidationError("tracking discovery configuration drift")
    if selection.provider_identity != previous.provider_identity:
        raise ContractValidationError("tracking provider identity drift")
    if selection.selection_policy_identity != previous.selection_policy_identity:
        raise ContractValidationError("tracking selection policy drift")
    if previous.tracking_policy_identity != policy.policy_identity:
        raise ContractValidationError("tracking policy identity drift")
    if selection.observed_at <= previous.observed_at:
        raise ContractValidationError("tracking observation time must be strictly increasing")
    if selection.input_identity == previous.input_identity:
        raise ContractValidationError("tracking input identity must advance")
    if selection.snapshot_id == previous.source_selection_snapshot_id:
        raise ContractValidationError("tracking source selection snapshot must be new")


def _family_for_candidate(
    candidate: Any,
    *,
    selection: CandidateSelectionSnapshot,
    policy: ExactSelectedStructureTrackingPolicy,
) -> str:
    return tracked_family_id(
        candidate,
        provider_identity=selection.provider_identity,
        discovery_config_identity=selection.discovery_config_identity,
        selection_policy_identity=selection.selection_policy_identity,
        tracking_policy_identity=policy.policy_identity,
    )


def _birth(
    candidate: Any,
    *,
    family_id: str,
    selection: CandidateSelectionSnapshot,
    policy: ExactSelectedStructureTrackingPolicy,
) -> TrackedTrendlineFamily:
    return TrackedTrendlineFamily(
        family_id=family_id,
        version=1,
        first_seen_at=selection.observed_at,
        last_seen_at=selection.observed_at,
        observation_count=1,
        current_candidate=candidate,
        current_selection_snapshot_id=selection.snapshot_id,
        provider_identity=selection.provider_identity,
        discovery_config_identity=selection.discovery_config_identity,
        selection_policy_identity=selection.selection_policy_identity,
        tracking_policy_identity=policy.policy_identity,
    )


def _continue(
    candidate: Any,
    previous: TrackedTrendlineFamily,
    *,
    selection: CandidateSelectionSnapshot,
    policy: ExactSelectedStructureTrackingPolicy,
) -> TrackedTrendlineFamily:
    return TrackedTrendlineFamily(
        family_id=previous.family_id,
        version=previous.version + 1,
        first_seen_at=previous.first_seen_at,
        last_seen_at=selection.observed_at,
        observation_count=previous.observation_count + 1,
        current_candidate=candidate,
        current_selection_snapshot_id=selection.snapshot_id,
        provider_identity=selection.provider_identity,
        discovery_config_identity=selection.discovery_config_identity,
        selection_policy_identity=selection.selection_policy_identity,
        tracking_policy_identity=policy.policy_identity,
    )


def _transition(
    *,
    family_id: str,
    transition_type: FamilyTrackingTransitionType,
    selection: CandidateSelectionSnapshot,
    policy: ExactSelectedStructureTrackingPolicy,
    previous_family: TrackedTrendlineFamily | None = None,
    current_family: TrackedTrendlineFamily | None = None,
) -> FamilyTrackingTransition:
    if transition_type is FamilyTrackingTransitionType.BIRTH:
        return FamilyTrackingTransition.create(
            family_id=family_id,
            transition_type=transition_type,
            observed_at=selection.observed_at,
            previous_family_version=None,
            current_family_version=current_family.version if current_family else None,
            previous_candidate_id=None,
            current_candidate_id=(
                current_family.current_candidate.candidate_id if current_family else None
            ),
            previous_selection_snapshot_id=None,
            current_selection_snapshot_id=selection.snapshot_id,
            tracking_policy_identity=policy.policy_identity,
        )
    if previous_family is None:
        raise ContractValidationError("non-birth transition requires previous family")
    if transition_type is FamilyTrackingTransitionType.CONTINUE:
        if current_family is None:
            raise ContractValidationError("continuation requires current family")
        return FamilyTrackingTransition.create(
            family_id=family_id,
            transition_type=transition_type,
            observed_at=selection.observed_at,
            previous_family_version=previous_family.version,
            current_family_version=current_family.version,
            previous_candidate_id=previous_family.current_candidate.candidate_id,
            current_candidate_id=current_family.current_candidate.candidate_id,
            previous_selection_snapshot_id=previous_family.current_selection_snapshot_id,
            current_selection_snapshot_id=selection.snapshot_id,
            tracking_policy_identity=policy.policy_identity,
        )
    return FamilyTrackingTransition.create(
        family_id=family_id,
        transition_type=transition_type,
        observed_at=selection.observed_at,
        previous_family_version=previous_family.version,
        current_family_version=None,
        previous_candidate_id=previous_family.current_candidate.candidate_id,
        current_candidate_id=None,
        previous_selection_snapshot_id=previous_family.current_selection_snapshot_id,
        current_selection_snapshot_id=selection.snapshot_id,
        tracking_policy_identity=policy.policy_identity,
    )


def _build_unavailable_snapshot(
    selection: CandidateSelectionSnapshot,
    *,
    previous: TrendlineTrackingSnapshot | None,
    policy: ExactSelectedStructureTrackingPolicy,
) -> TrendlineTrackingSnapshot:
    active = previous.active_families if previous is not None else ()
    removed = previous.removed_family_ids if previous is not None else ()
    previous_active_count = len(active)
    return TrendlineTrackingSnapshot(
        asset=selection.asset,
        timeframe=selection.timeframe,
        observed_at=selection.observed_at,
        previous_tracking_snapshot_id=previous.snapshot_id if previous is not None else None,
        source_selection_snapshot_id=selection.snapshot_id,
        input_identity=selection.input_identity,
        discovery_config_identity=selection.discovery_config_identity,
        provider_identity=selection.provider_identity,
        selection_policy_identity=selection.selection_policy_identity,
        tracking_policy_identity=policy.policy_identity,
        status=TrackingStatus.SOURCE_UNAVAILABLE,
        source_selection_status=selection.status,
        source_reason=selection.source_reason,
        active_families=active,
        removed_family_ids=removed,
        transitions=(),
        diagnostics=TrackingDiagnostics(
            previous_active_count=previous_active_count,
            source_selected_candidate_count=0,
            current_active_count=previous_active_count,
            birth_count=0,
            continuation_count=0,
            source_removed_count=0,
            carried_forward_count=previous_active_count,
            cumulative_removed_count=len(removed),
        ),
    )


def track_selected_trendlines(
    selection: CandidateSelectionSnapshot,
    *,
    previous: TrendlineTrackingSnapshot | None,
    policy: ExactSelectedStructureTrackingPolicy,
) -> TrendlineTrackingSnapshot:
    """Apply one pure exact-family lineage update."""

    _validate_previous_binding(selection, previous, policy)
    if selection.status is not SelectionStatus.SELECTED:
        return _build_unavailable_snapshot(selection, previous=previous, policy=policy)

    previous_active = {
        family.family_id: family
        for family in previous.active_families
    } if previous is not None else {}
    previous_removed = set(previous.removed_family_ids) if previous is not None else set()
    active: dict[str, TrackedTrendlineFamily] = {}
    transitions: list[FamilyTrackingTransition] = []
    seen: set[str] = set()

    for candidate in selection.selected_candidates:
        family_id = _family_for_candidate(candidate, selection=selection, policy=policy)
        if family_id in seen:
            raise ContractValidationError("duplicate tracked family identity in selected source")
        seen.add(family_id)
        if family_id in previous_removed:
            raise ContractValidationError("unsupported_removed_family_reappearance")
        previous_family = previous_active.get(family_id)
        if previous_family is None:
            family = _birth(
                candidate,
                family_id=family_id,
                selection=selection,
                policy=policy,
            )
            transitions.append(
                _transition(
                    family_id=family_id,
                    transition_type=FamilyTrackingTransitionType.BIRTH,
                    selection=selection,
                    policy=policy,
                    current_family=family,
                )
            )
        else:
            family = _continue(
                candidate,
                previous_family,
                selection=selection,
                policy=policy,
            )
            transitions.append(
                _transition(
                    family_id=family_id,
                    transition_type=FamilyTrackingTransitionType.CONTINUE,
                    selection=selection,
                    policy=policy,
                    previous_family=previous_family,
                    current_family=family,
                )
            )
        active[family_id] = family

    removed_now = set(previous_active) - set(active)
    removed = tuple(sorted(previous_removed | removed_now))
    for family_id in sorted(removed_now):
        transitions.append(
            _transition(
                family_id=family_id,
                transition_type=FamilyTrackingTransitionType.SOURCE_REMOVED,
                selection=selection,
                policy=policy,
                previous_family=previous_active[family_id],
            )
        )

    transitions.sort(key=lambda item: item.family_id)
    active_values = tuple(active[family_id] for family_id in sorted(active))
    birth_count = sum(
        item.transition_type is FamilyTrackingTransitionType.BIRTH for item in transitions
    )
    continuation_count = sum(
        item.transition_type is FamilyTrackingTransitionType.CONTINUE
        for item in transitions
    )
    source_removed_count = sum(
        item.transition_type is FamilyTrackingTransitionType.SOURCE_REMOVED
        for item in transitions
    )
    return TrendlineTrackingSnapshot(
        asset=selection.asset,
        timeframe=selection.timeframe,
        observed_at=selection.observed_at,
        previous_tracking_snapshot_id=previous.snapshot_id if previous is not None else None,
        source_selection_snapshot_id=selection.snapshot_id,
        input_identity=selection.input_identity,
        discovery_config_identity=selection.discovery_config_identity,
        provider_identity=selection.provider_identity,
        selection_policy_identity=selection.selection_policy_identity,
        tracking_policy_identity=policy.policy_identity,
        status=TrackingStatus.UPDATED,
        source_selection_status=selection.status,
        source_reason=None,
        active_families=active_values,
        removed_family_ids=removed,
        transitions=tuple(transitions),
        diagnostics=TrackingDiagnostics(
            previous_active_count=len(previous_active),
            source_selected_candidate_count=len(selection.selected_candidates),
            current_active_count=len(active_values),
            birth_count=birth_count,
            continuation_count=continuation_count,
            source_removed_count=source_removed_count,
            carried_forward_count=0,
            cumulative_removed_count=len(removed),
        ),
    )


__all__ = ["track_selected_trendlines", "tracked_family_id"]
