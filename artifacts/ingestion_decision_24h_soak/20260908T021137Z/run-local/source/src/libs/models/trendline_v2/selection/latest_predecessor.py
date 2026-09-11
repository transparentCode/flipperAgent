"""Canonical latest-valid-predecessor selection policy."""

from __future__ import annotations

from collections import defaultdict

from ..domain.enums import DiscoveryStatus
from ..domain.identity import require_hash
from ..domain.snapshots import DiscoverySnapshot
from ..domain.validation import ContractValidationError
from .contracts import (
    CandidateSelectionDecision,
    CandidateSelectionSnapshot,
    LatestValidPredecessorPolicy,
    SelectionDiagnostics,
    SelectionStatus,
    candidate_set_identity,
)


def _source_outcome(
    snapshot: DiscoverySnapshot,
    *,
    policy: LatestValidPredecessorPolicy,
) -> CandidateSelectionSnapshot:
    if snapshot.status is DiscoveryStatus.ABSTAINED:
        status = SelectionStatus.SOURCE_ABSTAINED
    elif snapshot.status is DiscoveryStatus.FAILED:
        status = SelectionStatus.SOURCE_FAILED
    else:
        raise ContractValidationError("source outcome helper requires a non-valid snapshot")
    return CandidateSelectionSnapshot(
        asset=snapshot.asset,
        timeframe=snapshot.timeframe,
        observed_at=snapshot.observed_at,
        source_snapshot_id=snapshot.snapshot_id,
        input_identity=snapshot.input_identity,
        discovery_config_identity=snapshot.config_identity,
        provider_identity=snapshot.provider_identity,
        selection_policy_identity=policy.policy_identity,
        status=status,
        source_reason=snapshot.reason,
        source_candidate_set_identity=candidate_set_identity(()),
        selected_candidates=(),
        decisions=(),
        diagnostics=SelectionDiagnostics(0, 0, 0, 0, 0, 0, 0),
    )


def select_latest_valid_predecessors(
    snapshot: DiscoverySnapshot,
    *,
    policy: LatestValidPredecessorPolicy,
) -> CandidateSelectionSnapshot:
    """Select one latest predecessor for each role/second-anchor group."""

    if not isinstance(snapshot, DiscoverySnapshot):
        raise ContractValidationError("selection.snapshot must be DiscoverySnapshot")
    if not isinstance(policy, LatestValidPredecessorPolicy):
        raise ContractValidationError(
            "selection.policy must be LatestValidPredecessorPolicy"
        )
    if snapshot.status is not DiscoveryStatus.VALID:
        return _source_outcome(snapshot, policy=policy)
    if snapshot.provider_identity != policy.supported_provider_identity:
        raise ContractValidationError("selection source provider is unsupported")

    grouped = defaultdict(list)
    for candidate in snapshot.candidates:
        if (
            candidate.provider_name != policy.supported_provider_name
            or candidate.provider_version != policy.supported_provider_version
        ):
            raise ContractValidationError("candidate provider is unsupported")
        if len(candidate.anchors) != policy.required_anchor_count:
            raise ContractValidationError("selection candidates require exactly two anchors")
        for anchor in candidate.anchors:
            require_hash(anchor.anchor_id, field_name="selection.anchor_id")
        second_anchor = candidate.anchors[1]
        grouped[(candidate.role, second_anchor.anchor_id)].append(candidate)

    selected: list[object] = []
    decisions: list[CandidateSelectionDecision] = []
    tie_group_count = 0
    for (role, second_anchor_id), candidates in grouped.items():
        second_anchor = candidates[0].anchors[1]
        if any(candidate.anchors[1] != second_anchor for candidate in candidates[1:]):
            raise ContractValidationError("second-anchor representations are inconsistent")
        latest_time = max(candidate.anchors[0].pivot_time for candidate in candidates)
        latest = [candidate for candidate in candidates if candidate.anchors[0].pivot_time == latest_time]
        if len(latest) > 1:
            tie_group_count += 1
        winner = min(
            latest,
            key=lambda candidate: (
                candidate.anchors[0].anchor_id,
                candidate.candidate_id,
            ),
        )
        considered_ids = tuple(sorted(candidate.candidate_id for candidate in candidates))
        decisions.append(
            CandidateSelectionDecision.create(
                role=role,
                second_anchor_id=second_anchor_id,
                second_anchor_time=second_anchor.pivot_time,
                considered_candidate_ids=considered_ids,
                selected_candidate_id=winner.candidate_id,
                selected_first_anchor_id=winner.anchors[0].anchor_id,
                selected_first_anchor_time=winner.anchors[0].pivot_time,
                latest_timestamp_tie_count=len(latest),
                selection_policy_identity=policy.policy_identity,
            )
        )
        selected.append(winner)

    selected_candidates = tuple(
        sorted(
            selected,
            key=lambda candidate: (
                candidate.role.value,
                candidate.anchors[1].pivot_time,
                candidate.anchors[1].anchor_id,
                candidate.candidate_id,
            ),
        )
    )
    decisions_by_candidate = {
        decision.selected_candidate_id: decision for decision in decisions
    }
    ordered_decisions = tuple(
        decisions_by_candidate[candidate.candidate_id] for candidate in selected_candidates
    )
    diagnostics = SelectionDiagnostics(
        source_candidate_count=len(snapshot.candidates),
        source_group_count=len(grouped),
        selected_candidate_count=len(selected_candidates),
        rejected_candidate_count=len(snapshot.candidates) - len(selected_candidates),
        support_selected_count=sum(
            candidate.role.value == "support" for candidate in selected_candidates
        ),
        resistance_selected_count=sum(
            candidate.role.value == "resistance" for candidate in selected_candidates
        ),
        latest_timestamp_tie_group_count=tie_group_count,
    )
    return CandidateSelectionSnapshot(
        asset=snapshot.asset,
        timeframe=snapshot.timeframe,
        observed_at=snapshot.observed_at,
        source_snapshot_id=snapshot.snapshot_id,
        input_identity=snapshot.input_identity,
        discovery_config_identity=snapshot.config_identity,
        provider_identity=snapshot.provider_identity,
        selection_policy_identity=policy.policy_identity,
        status=SelectionStatus.SELECTED,
        source_reason=None,
        source_candidate_set_identity=candidate_set_identity(
            tuple(candidate.candidate_id for candidate in snapshot.candidates)
        ),
        selected_candidates=selected_candidates,
        decisions=ordered_decisions,
        diagnostics=diagnostics,
    )


__all__ = ["select_latest_valid_predecessors"]
