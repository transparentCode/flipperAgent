"""Additive shadow-feature projection from persisted MTF snapshots."""

from __future__ import annotations

import math
from typing import Any, Iterable

from ..domain.enums import FamilyRole
from ..domain.validation import ContractValidationError
from .contracts import (
    MTFCluster,
    MTFFreshnessState,
    MTFGeometrySnapshot,
    MTFNormalizationContext,
    MTFRelationType,
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
