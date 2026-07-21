"""Project immutable single-timeframe families and exact member rails."""

from __future__ import annotations

from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from ..domain.geometry import LineGeometry
from ..domain.identity import deterministic_hash, deterministic_id
from ..domain.snapshots import TrendlineFamilySnapshot
from ..domain.validation import ContractValidationError
from .contracts import (
    MTFFreshnessState,
    MTFNormalizationContext,
    MTFSourceSnapshotAudit,
    MTFSourceSnapshotReference,
    ProjectedMTFFamily,
    ProjectedMTFMember,
    _projected_family_sort_key,
)

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
