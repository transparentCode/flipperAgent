"""Deterministic tables from persisted canonical research evidence."""

from __future__ import annotations

from typing import Mapping, Sequence

from ..contracts import ContractValidationError, TrendlineFamilySnapshot, deterministic_hash
from ..mtf import MTFGeometrySnapshot
from ..optimization.contracts import TrialResult
from .contracts import (
    ArtifactTrialRow,
    CandidateRow,
    CandidateStatusRow,
    CorridorRow,
    CrossAssetComparabilityAudit,
    CrossAssetComparabilityPolicy,
    CrossAssetComparison,
    CrossAssetComparisonRow,
    EventRow,
    EventTransitionRow,
    FamilyRow,
    InteractionZoneRow,
    MTFClusterRow,
    MTFProjectedFamilyRow,
    MTFProjectedMemberRow,
    MTFRelationRow,
    MTFSourceRow,
    MemberRailRow,
    ObservationRow,
    ProviderAuditRow,
    SnapshotSummary,
    SourceGroupAuditRow,
    StructuralOutcomeRow,
    TransitionRow,
)
from .replay import ResearchReplay


def _group_corridors(snapshot: TrendlineFamilySnapshot) -> dict[str, tuple]:
    grouped: dict[str, list] = {}
    for corridor in snapshot.corridors:
        grouped.setdefault(corridor.family_id, []).append(corridor)
    return {family_id: tuple(items) for family_id, items in grouped.items()}


def _family_corridor_width(corridors: tuple) -> float | None:
    return corridors[0].width_atr if len(corridors) == 1 else None


def _family_corridor_status(corridors: tuple) -> str:
    if not corridors:
        return "NO_CORRIDOR"
    if len(corridors) == 1:
        return "SINGLE_CORRIDOR"
    return "MULTIPLE_CORRIDORS"


def snapshot_summary(snapshot: TrendlineFamilySnapshot) -> SnapshotSummary:
    return SnapshotSummary(
        snapshot_id=snapshot.snapshot_id,
        previous_snapshot_id=snapshot.previous_snapshot_id,
        timestamp=snapshot.timestamp,
        active_family_count=len(snapshot.active_families),
        dormant_family_count=len(snapshot.dormant_families),
        transition_count=len(snapshot.transitions),
        corridor_count=len(snapshot.corridors),
        observation_count=len(snapshot.observations),
        event_count=len(snapshot.interaction_events),
        diagnostics=dict(snapshot.diagnostics),
    )


def candidate_rows(replay: ResearchReplay) -> tuple[CandidateRow, ...]:
    rows = tuple(
        CandidateRow(
            timestamp=timestamp,
            candidate_id=candidate.candidate_id,
            role=candidate.role.value,
            provider=candidate.provider,
            method=candidate.method,
            anchor_count=len(candidate.anchors),
            anchor_kinds=tuple(anchor.pivot_kind for anchor in candidate.anchors),
            slope_per_second=candidate.geometry.slope_per_second,
            normalized_quality=candidate.diagnostics.normalized_quality,
            coverage=candidate.diagnostics.coverage,
            residual_scale_atr=candidate.diagnostics.residual_scale_atr,
            source_line_index=candidate.source_line_index,
        )
        for timestamp, result in zip(replay.dataset.timestamps, replay.candidate_results, strict=True)
        for candidate in result.candidates
    )
    return tuple(sorted(rows, key=lambda row: (row.timestamp, row.role, row.candidate_id)))


def candidate_status_rows(replay: ResearchReplay) -> tuple[CandidateStatusRow, ...]:
    return tuple(
        CandidateStatusRow(
            timestamp=timestamp,
            status=result.status.value,
            candidate_count=len(result.candidates),
            reason_codes=result.reason_codes,
        )
        for timestamp, result in zip(replay.dataset.timestamps, replay.candidate_results, strict=True)
    )


def provider_audit_rows(replay: ResearchReplay) -> tuple[ProviderAuditRow, ...]:
    """Surface canonical provider metadata without interpreting it as model truth."""

    rows = tuple(
        ProviderAuditRow(
            timestamp=timestamp,
            status=result.status.value,
            candidate_count=len(result.candidates),
            reason_codes=result.reason_codes,
            confirmed_bar_count=_metadata_int(result.metadata, "confirmed_bars"),
            confirmed_pivot_count=_metadata_int(result.metadata, "confirmed_pivots"),
            fitted_path_count=_metadata_int(result.metadata, "fitted_paths"),
            fit_status=_metadata_text(result.metadata, "fit_status"),
        )
        for timestamp, result in zip(replay.dataset.timestamps, replay.candidate_results, strict=True)
    )
    return tuple(sorted(rows, key=lambda row: row.timestamp))


def family_rows(snapshot: TrendlineFamilySnapshot) -> tuple[FamilyRow, ...]:
    corridors_by_family = {
        family_id: tuple(sorted(items, key=lambda item: item.corridor_id))
        for family_id, items in _group_corridors(snapshot).items()
    }
    rows = tuple(
        FamilyRow(
            snapshot_id=snapshot.snapshot_id,
            timestamp=snapshot.timestamp,
            family_id=family.family_id,
            role=family.current_role.value,
            lifecycle=family.lifecycle_state.value,
            confidence=family.confidence,
            age_bars=family.age_bars,
            representative_member_id=family.representative_member_id,
            member_count=len(family.members),
            structural_importance=family.structural_importance,
            current_relevance=family.current_relevance,
            touch_count=family.touch_count,
            breach_count=family.breach_count,
            corridor_width_atr=_family_corridor_width(corridors_by_family.get(family.family_id, ())),
            corridor_status=_family_corridor_status(corridors_by_family.get(family.family_id, ())),
        )
        for family in snapshot.active_families + snapshot.dormant_families
    )
    return tuple(sorted(rows, key=lambda row: (row.role, row.family_id)))


def member_rail_rows(snapshot: TrendlineFamilySnapshot) -> tuple[MemberRailRow, ...]:
    rows = tuple(
        MemberRailRow(
            snapshot_id=snapshot.snapshot_id,
            timestamp=snapshot.timestamp,
            family_id=family.family_id,
            member_id=member.member_id,
            candidate_id=member.candidate_id,
            role=family.current_role.value,
            lifecycle=family.lifecycle_state.value,
            representative=member.member_id == family.representative_member_id,
            confidence=family.confidence,
            age_bars=family.age_bars,
            projected_price=member.geometry.value_at(snapshot.timestamp),
            reference_time=member.geometry.reference_time,
            reference_price=member.geometry.reference_price,
            slope_per_second=member.geometry.slope_per_second,
            anchor_ids=tuple(anchor.anchor_id for anchor in member.anchors),
            anchor_points=tuple((anchor.timestamp, anchor.price, anchor.pivot_kind) for anchor in member.anchors),
        )
        for family in snapshot.active_families + snapshot.dormant_families
        for member in family.members
    )
    return tuple(sorted(rows, key=lambda row: (row.role, row.family_id, row.member_id)))


def corridor_rows(snapshot: TrendlineFamilySnapshot) -> tuple[CorridorRow, ...]:
    rows = tuple(
        CorridorRow(
            snapshot_id=snapshot.snapshot_id,
            timestamp=snapshot.timestamp,
            corridor_id=corridor.corridor_id,
            family_id=corridor.family_id,
            role=corridor.role.value,
            lower_price=corridor.lower_price,
            upper_price=corridor.upper_price,
            center_price=corridor.center_price,
            width_atr=corridor.width_atr,
            rail_count=corridor.rail_count,
            ordered_member_ids=corridor.ordered_member_ids,
        )
        for corridor in snapshot.corridors
    )
    return tuple(sorted(rows, key=lambda row: (row.role, row.family_id, row.corridor_id)))


def interaction_zone_rows(snapshot: TrendlineFamilySnapshot) -> tuple[InteractionZoneRow, ...]:
    rows = tuple(
        InteractionZoneRow(
            snapshot_id=snapshot.snapshot_id,
            timestamp=snapshot.timestamp,
            observation_id=observation.observation_id,
            family_id=observation.family_id,
            role=observation.role.value,
            exact_line_price=observation.exact_line_price,
            lower_price=observation.zone.lower_price,
            upper_price=observation.zone.upper_price,
            width_atr=observation.zone.width_atr,
            observation_state=observation.state.value,
        )
        for observation in snapshot.observations
    )
    return tuple(sorted(rows, key=lambda row: (row.role, row.family_id, row.observation_id)))


def transition_rows(snapshot: TrendlineFamilySnapshot) -> tuple[TransitionRow, ...]:
    rows = tuple(
        TransitionRow(
            snapshot_id=snapshot.snapshot_id,
            timestamp=transition.timestamp,
            transition_id=transition.transition_id,
            family_id=transition.family_id,
            transition_type=transition.transition_type.value,
            previous_version=transition.previous_version,
            new_version=transition.new_version,
            reason_codes=transition.reason_codes,
            added_member_ids=transition.added_member_ids,
            continued_member_ids=transition.continued_member_ids,
            removed_member_ids=transition.removed_member_ids,
            representative_changed=transition.representative_changed,
            source_group_id=transition.source_group_id,
            source_group_candidate_ids=transition.source_group_candidate_ids,
        )
        for transition in snapshot.transitions
    )
    return tuple(sorted(rows, key=lambda row: (row.timestamp, row.family_id, row.transition_id)))


def observation_rows(snapshot: TrendlineFamilySnapshot) -> tuple[ObservationRow, ...]:
    rows = tuple(
        ObservationRow(
            snapshot_id=snapshot.snapshot_id,
            timestamp=observation.timestamp,
            observation_id=observation.observation_id,
            family_id=observation.family_id,
            role=observation.role.value,
            state=observation.state.value,
            exact_line_price=observation.exact_line_price,
            distance_to_line_atr=observation.distance_to_line_atr,
            distance_to_zone_atr=observation.distance_to_zone_atr,
            wick_penetration_atr=observation.wick_penetration_atr,
            body_penetration_atr=observation.body_penetration_atr,
            close_penetration_atr=observation.close_penetration_atr,
        )
        for observation in snapshot.observations
    )
    return tuple(sorted(rows, key=lambda row: (row.timestamp, row.family_id, row.observation_id)))


def event_rows(snapshot: TrendlineFamilySnapshot) -> tuple[EventRow, ...]:
    rows = tuple(
        EventRow(
            snapshot_id=snapshot.snapshot_id,
            timestamp=snapshot.timestamp,
            event_id=event.event_id,
            family_id=event.family_id,
            state=event.state.value,
            previous_state=None if event.previous_state is None else event.previous_state.value,
            started_at=event.started_at,
            updated_at=event.updated_at,
            age_bars=event.age_bars,
            last_observation_id=event.last_observation_id,
        )
        for event in snapshot.interaction_events
    )
    return tuple(sorted(rows, key=lambda row: (row.updated_at, row.family_id, row.event_id)))


def event_transition_rows(snapshot: TrendlineFamilySnapshot) -> tuple[EventTransitionRow, ...]:
    rows = tuple(
        EventTransitionRow(
            snapshot_id=snapshot.snapshot_id,
            timestamp=transition.timestamp,
            transition_id=transition.transition_id,
            event_id=transition.event_id,
            family_id=transition.family_id,
            from_state=transition.from_state.value,
            to_state=transition.to_state.value,
            trigger_observation_id=transition.trigger_observation_id,
            reason_code=transition.reason_code,
        )
        for transition in snapshot.interaction_event_transitions
    )
    return tuple(sorted(rows, key=lambda row: (row.timestamp, row.family_id, row.event_id, row.transition_id)))


def family_lineage_rows(replay: ResearchReplay, *, family_id: str) -> tuple[TransitionRow, ...]:
    rows = tuple(
        row
        for output in replay.outputs
        for row in transition_rows(output.snapshot)
        if row.family_id == family_id
    )
    return tuple(sorted(rows, key=lambda row: (row.timestamp, row.new_version, row.transition_id)))


def replay_family_rows(replay: ResearchReplay) -> tuple[FamilyRow, ...]:
    return tuple(row for output in replay.outputs for row in family_rows(output.snapshot))


def replay_member_rail_rows(replay: ResearchReplay) -> tuple[MemberRailRow, ...]:
    return tuple(row for output in replay.outputs for row in member_rail_rows(output.snapshot))


def replay_corridor_rows(replay: ResearchReplay) -> tuple[CorridorRow, ...]:
    return tuple(row for output in replay.outputs for row in corridor_rows(output.snapshot))


def audit_cross_asset_comparability(
    replays: Sequence[ResearchReplay],
    *,
    policy: CrossAssetComparabilityPolicy,
) -> CrossAssetComparabilityAudit:
    """Derive a typed audit from replay parameter and sample evidence."""

    if not isinstance(policy, CrossAssetComparabilityPolicy):
        raise ContractValidationError("cross-asset comparability requires typed policy")
    ordered = tuple(sorted(tuple(replays), key=lambda item: item.context.asset))
    if any(not isinstance(item, ResearchReplay) for item in ordered):
        raise ContractValidationError("cross-asset comparability requires ResearchReplay values")
    assets = tuple(item.context.asset for item in ordered)
    timeframes = tuple(item.context.timeframe for item in ordered)
    parameter_hashes = tuple(item.context.parameter_policy_hash for item in ordered)
    provider_hashes = tuple(deterministic_hash(item.context.provider_spec) for item in ordered)
    starts = tuple(item.dataset.timestamps[0] for item in ordered)
    ends = tuple(item.dataset.timestamps[-1] for item in ordered)
    row_counts = tuple(item.dataset.row_count for item in ordered)
    reasons: list[str] = []
    if len(ordered) < policy.minimum_asset_count:
        reasons.append("insufficient_asset_count")
    if len(set(assets)) != len(assets):
        reasons.append("duplicate_asset")
    if policy.require_same_timeframe and len(set(timeframes)) > 1:
        reasons.append("timeframe_mismatch")
    if policy.require_same_window and (len(set(starts)) > 1 or len(set(ends)) > 1):
        reasons.append("sample_window_mismatch")
    if policy.require_same_row_count and len(set(row_counts)) > 1:
        reasons.append("sample_row_count_mismatch")
    if policy.require_same_parameter_policy and len(set(parameter_hashes)) > 1:
        reasons.append("parameter_policy_mismatch")
    if policy.require_same_provider_spec and len(set(provider_hashes)) > 1:
        reasons.append("provider_policy_mismatch")
    return CrossAssetComparabilityAudit(
        policy_id=policy.policy_id,
        policy_identity=policy.identity_payload(),
        comparable=not reasons,
        reason_codes=tuple(reasons),
        assets=assets,
        timeframes=timeframes,
        parameter_policy_hashes=parameter_hashes,
        provider_spec_hashes=provider_hashes,
        sample_starts=starts,
        sample_ends=ends,
        row_counts=row_counts,
    )


def build_cross_asset_comparison(
    replays: Sequence[ResearchReplay],
    *,
    policy: CrossAssetComparabilityPolicy,
) -> CrossAssetComparison:
    """Build structural comparison rows only after the typed audit passes."""

    ordered = tuple(sorted(tuple(replays), key=lambda item: item.context.asset))
    audit = audit_cross_asset_comparability(ordered, policy=policy)
    if not audit.comparable:
        raise ContractValidationError(
            "cross-asset research samples are not comparable: " + ",".join(audit.reason_codes)
        )
    rows = tuple(
        CrossAssetComparisonRow(
            asset=item.context.asset,
            timeframe=item.context.timeframe,
            dataset_hash=item.context.dataset_hash,
            parameter_policy_hash=item.context.parameter_policy_hash,
            provider_spec_hash=deterministic_hash(item.context.provider_spec),
            sample_start=item.dataset.timestamps[0],
            sample_end=item.dataset.timestamps[-1],
            eligible_bar_count=item.dataset.row_count,
            candidate_count=len(candidate_rows(item)),
            unique_family_count=len({row.family_id for row in replay_family_rows(item)}),
            family_snapshot_count=len(replay_family_rows(item)),
        )
        for item in ordered
    )
    return CrossAssetComparison(policy=policy, audit=audit, rows=rows)


def replay_transition_rows(replay: ResearchReplay) -> tuple[TransitionRow, ...]:
    return tuple(row for output in replay.outputs for row in transition_rows(output.snapshot))


def replay_observation_rows(replay: ResearchReplay) -> tuple[ObservationRow, ...]:
    return tuple(row for output in replay.outputs for row in observation_rows(output.snapshot))


def replay_event_rows(replay: ResearchReplay) -> tuple[EventRow, ...]:
    return tuple(row for output in replay.outputs for row in event_rows(output.snapshot))


def replay_event_transition_rows(replay: ResearchReplay) -> tuple[EventTransitionRow, ...]:
    return tuple(row for output in replay.outputs for row in event_transition_rows(output.snapshot))


def source_group_audit_rows(snapshot: TrendlineFamilySnapshot) -> tuple[SourceGroupAuditRow, ...]:
    rows = tuple(
        SourceGroupAuditRow(
            snapshot_id=snapshot.snapshot_id,
            timestamp=snapshot.timestamp,
            source_group_id=audit.source_group_id,
            role=audit.role.value,
            candidate_ids=audit.candidate_ids,
            candidate_content_hashes=audit.candidate_content_hashes,
        )
        for audit in snapshot.source_group_audits
    )
    return tuple(sorted(rows, key=lambda row: row.source_group_id))


def structural_outcome_rows(replay: ResearchReplay) -> tuple[StructuralOutcomeRow, ...]:
    """Persisted structural history only; forward policy outcomes remain explicitly unavailable."""

    history: dict[str, list[FamilyRow]] = {}
    events: dict[str, int] = {}
    for output in replay.outputs:
        for row in family_rows(output.snapshot):
            history.setdefault(row.family_id, []).append(row)
        for event in event_rows(output.snapshot):
            events[event.family_id] = events.get(event.family_id, 0) + 1
    rows = tuple(
        StructuralOutcomeRow(
            subject_type="family",
            subject_id=family_id,
            lifetime_bars=len(rows_for_family),
            dormant_snapshot_count=sum(row.lifecycle == "DORMANT" for row in rows_for_family),
            interaction_snapshot_count=events.get(family_id, 0),
            status="PERSISTED_HISTORY",
            reason_code=None,
        )
        for family_id, rows_for_family in history.items()
    )
    return tuple(sorted(rows, key=lambda row: row.subject_id))


def _metadata_text(metadata: object, key: str) -> str | None:
    value = metadata.get(key) if isinstance(metadata, Mapping) else None
    return value if isinstance(value, str) else None


def _metadata_int(metadata: object, key: str) -> int | None:
    value = metadata.get(key) if isinstance(metadata, Mapping) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def mtf_source_rows(snapshot: MTFGeometrySnapshot) -> tuple[MTFSourceRow, ...]:
    rows = tuple(
        MTFSourceRow(
            mtf_snapshot_id=snapshot.mtf_snapshot_id,
            decision_timestamp=snapshot.decision_timestamp,
            source_timeframe=status.source_timeframe,
            freshness_state=status.freshness_state.value,
            source_snapshot_id=status.source_snapshot_id,
            source_snapshot_timestamp=status.source_snapshot_timestamp,
            source_age_bars=status.source_age_bars,
            reason_codes=status.reason_codes,
        )
        for status in snapshot.source_statuses
    )
    return tuple(sorted(rows, key=lambda row: row.source_timeframe))


def mtf_projected_family_rows(snapshot: MTFGeometrySnapshot) -> tuple[MTFProjectedFamilyRow, ...]:
    """Expose canonical projected-family audit fields without recomputing them."""

    rows = tuple(
        MTFProjectedFamilyRow(
            mtf_snapshot_id=snapshot.mtf_snapshot_id,
            projected_family_id=family.projected_family_id,
            source_snapshot_id=family.source_snapshot_id,
            source_timeframe=family.source_timeframe,
            source_family_id=family.source_family_id,
            source_family_version=family.source_family_version,
            role=family.source_family_role.value,
            lifecycle=family.source_family_lifecycle.value,
            representative_member_id=family.source_representative_member_id,
            projected_representative_price=family.projected_representative_price,
            projected_representative_slope_per_second=family.projected_representative_slope_per_second,
            projected_corridor_lower_price=family.projected_corridor_lower_price,
            projected_corridor_upper_price=family.projected_corridor_upper_price,
            projected_corridor_width_atr=family.projected_corridor_width_atr,
            source_confidence=family.source_confidence,
            source_structural_importance=family.source_structural_importance,
            source_event_id=family.source_event_id,
            source_event_state=family.source_event_state,
            source_age_bars=family.source_age_bars,
            freshness_state=family.freshness_state.value,
            contributes_to_confluence=family.contributes_to_confluence,
            projected_order_changed=family.projected_order_changed,
            projection_timestamp=family.projection_timestamp,
        )
        for family in snapshot.projected_families
    )
    return tuple(sorted(rows, key=lambda row: (row.source_timeframe, row.role, row.projected_family_id)))


def mtf_projected_member_rows(snapshot: MTFGeometrySnapshot) -> tuple[MTFProjectedMemberRow, ...]:
    """Expose exact projected member geometry, not an averaged research rail."""

    rows = tuple(
        MTFProjectedMemberRow(
            mtf_snapshot_id=snapshot.mtf_snapshot_id,
            projected_member_id=member.projected_member_id,
            projected_family_id=member.projected_family_id,
            source_snapshot_id=member.source_snapshot_id,
            source_timeframe=member.source_timeframe,
            source_family_id=member.source_family_id,
            source_member_id=member.source_member_id,
            source_candidate_id=member.source_candidate_id,
            reference_time=member.source_geometry.reference_time,
            reference_price=member.source_geometry.reference_price,
            slope_per_second=member.source_geometry.slope_per_second,
            projected_price=member.projected_price,
            projected_offset_from_representative=member.projected_offset_from_representative,
            source_order_index=member.source_order_index,
            projection_timestamp=member.projection_timestamp,
        )
        for member in snapshot.projected_members
    )
    return tuple(sorted(rows, key=lambda row: (row.source_timeframe, row.projected_family_id, row.source_order_index, row.projected_member_id)))


def mtf_relation_rows(snapshot: MTFGeometrySnapshot) -> tuple[MTFRelationRow, ...]:
    rows = tuple(
        MTFRelationRow(
            mtf_snapshot_id=snapshot.mtf_snapshot_id,
            relation_id=relation.relation_id,
            relation_type=relation.relation_type.value,
            left_projected_family_id=relation.left_projected_family_id,
            right_projected_family_id=relation.right_projected_family_id,
            left_source_timeframe=relation.left_source_timeframe,
            right_source_timeframe=relation.right_source_timeframe,
            intersection_timestamp=relation.intersection_timestamp,
            intersection_price=relation.intersection_price,
            reason_codes=relation.reason_codes,
        )
        for relation in snapshot.relations
    )
    return tuple(sorted(rows, key=lambda row: row.relation_id))


def mtf_cluster_rows(snapshot: MTFGeometrySnapshot) -> tuple[MTFClusterRow, ...]:
    rows = tuple(
        MTFClusterRow(
            mtf_snapshot_id=snapshot.mtf_snapshot_id,
            cluster_id=cluster.cluster_id,
            role=cluster.role.value,
            projected_family_ids=cluster.projected_family_ids,
            source_timeframes=cluster.source_timeframes,
            confluence_strength=cluster.confluence_strength,
            is_confluence=cluster.is_confluence,
            freshness_summary=cluster.freshness_summary,
        )
        for cluster in snapshot.clusters
    )
    return tuple(sorted(rows, key=lambda row: row.cluster_id))


def artifact_trial_rows(trials: Sequence[TrialResult]) -> tuple[ArtifactTrialRow, ...]:
    rows = tuple(
        ArtifactTrialRow(
            trial_id=result.trial.trial_id,
            result_id=result.result_id,
            stage=result.trial.stage.value,
            status=result.status.value,
            overrides=dict(result.trial.parameter_overrides),
            primary_metric_name=result.trial.objective.primary_metric,
            primary_metric_value=None if result.metric(result.trial.objective.primary_metric) is None else result.metric(result.trial.objective.primary_metric).value,
            worst_metric_value=None if result.metric(f"{result.trial.objective.primary_metric}__worst") is None else result.metric(f"{result.trial.objective.primary_metric}__worst").value,
            validation_only=all(window.window_kind == "validation" for window in result.window_results),
            rejection_reasons=() if result.objective_gate is None else result.objective_gate.rejection_reasons,
            aggregate_metrics={name: metric.to_dict() for name, metric in result.aggregate_metrics.items()},
            per_window_metrics=tuple(window.to_dict() for window in result.window_results),
            counterfactual_result_ids=tuple(counterfactual.result_id for counterfactual in result.counterfactual_results),
            parameter_audits=tuple(audit.to_dict() for audit in result.parameter_effect_audits),
        )
        for result in trials
    )
    return tuple(sorted(rows, key=lambda row: row.trial_id))


__all__ = [
    "artifact_trial_rows",
    "audit_cross_asset_comparability",
    "build_cross_asset_comparison",
    "candidate_rows",
    "candidate_status_rows",
    "corridor_rows",
    "event_rows",
    "event_transition_rows",
    "family_lineage_rows",
    "family_rows",
    "interaction_zone_rows",
    "member_rail_rows",
    "mtf_cluster_rows",
    "mtf_projected_family_rows",
    "mtf_projected_member_rows",
    "mtf_relation_rows",
    "mtf_source_rows",
    "observation_rows",
    "provider_audit_rows",
    "replay_event_rows",
    "replay_event_transition_rows",
    "replay_family_rows",
    "replay_member_rail_rows",
    "replay_observation_rows",
    "replay_transition_rows",
    "replay_corridor_rows",
    "snapshot_summary",
    "source_group_audit_rows",
    "structural_outcome_rows",
    "transition_rows",
]
