"""Deterministic complete-linkage MTF cluster construction."""

from __future__ import annotations

from datetime import datetime

from ..domain.enums import FamilyLifecycleState
from ..domain.identity import deterministic_id
from .contracts import (
    MTFCluster,
    MTFFreshnessState,
    MTFNormalizationContext,
    MTFPolicyAudit,
    MTFRelation,
    MTFRelationType,
    ProjectedMTFFamily,
    _FLOAT_TOLERANCE,
    _projected_family_sort_key,
    _timeframe_key,
)

def _build_clusters(
    *,
    families: tuple[ProjectedMTFFamily, ...],
    relations: tuple[MTFRelation, ...],
    decision_timestamp: datetime,
    normalization_context: MTFNormalizationContext,
    policy: MTFPolicyAudit,
    asset: str,
    model_version: str,
    config_version: str,
    mtf_config_hash: str,
) -> tuple[MTFCluster, ...]:
    compatible_pairs = {
        frozenset((relation.left_projected_family_id, relation.right_projected_family_id))
        for relation in relations
        if relation.relation_type in {MTFRelationType.AGREEMENT, MTFRelationType.CONFLUENCE, MTFRelationType.NESTED}
    }
    remaining = [
        family
        for family in families
        if family.contributes_to_confluence and family.source_family_lifecycle is FamilyLifecycleState.ACTIVE
    ]
    clusters: list[MTFCluster] = []
    while remaining:
        seed = remaining.pop(0)
        selected = [seed]
        for candidate in tuple(remaining):
            if candidate.source_family_role is not seed.source_family_role or candidate.source_timeframe in {item.source_timeframe for item in selected}:
                continue
            if all(frozenset((candidate.projected_family_id, member.projected_family_id)) in compatible_pairs for member in selected):
                selected.append(candidate)
                remaining.remove(candidate)
        clusters.append(
            _make_cluster(
                selected=tuple(sorted(selected, key=_projected_family_sort_key)),
                relations=relations,
                decision_timestamp=decision_timestamp,
                normalization_context=normalization_context,
                policy=policy,
                asset=asset,
                model_version=model_version,
                config_version=config_version,
                mtf_config_hash=mtf_config_hash,
            )
        )
    return tuple(sorted(clusters, key=lambda item: item.cluster_id))


def _make_cluster(
    *,
    selected: tuple[ProjectedMTFFamily, ...],
    relations: tuple[MTFRelation, ...],
    decision_timestamp: datetime,
    normalization_context: MTFNormalizationContext,
    policy: MTFPolicyAudit,
    asset: str,
    model_version: str,
    config_version: str,
    mtf_config_hash: str,
) -> MTFCluster:
    ids = tuple(sorted(item.projected_family_id for item in selected))
    by_pair = {
        frozenset((relation.left_projected_family_id, relation.right_projected_family_id)): relation
        for relation in relations
    }
    pair_relations = [
        by_pair[frozenset((left.projected_family_id, right.projected_family_id))]
        for index, left in enumerate(selected)
        for right in selected[index + 1 :]
    ]
    prices = [item.projected_representative_price for item in selected]
    slopes = [item.normalized_slope_atr_per_hour for item in selected]
    level_dispersion = None if len(selected) == 1 else (max(prices) - min(prices)) / normalization_context.atr
    slope_dispersion = None if len(selected) == 1 or any(item is None for item in slopes) else max(slopes) - min(slopes)
    overlap = None if not pair_relations else min(relation.corridor_overlap_ratio or 0.0 for relation in pair_relations)
    timeframe_count = len({item.source_timeframe for item in selected})
    is_confluence = timeframe_count >= policy.minimum_confluence_timeframes
    freshness_states = {item.freshness_state for item in selected}
    freshness_summary = next(iter(freshness_states)).value if len(freshness_states) == 1 else "MIXED"
    if len(selected) == 1:
        confluence_strength = None
    else:
        freshness_multiplier = 1.0 if freshness_states == {MTFFreshnessState.FRESH} else 0.75
        confidence = sum(item.source_confidence * item.source_structural_importance for item in selected) / len(selected)
        closeness = 1.0 - min((level_dispersion or 0.0) / max(policy.max_level_distance_atr, _FLOAT_TOLERANCE), 1.0)
        confluence_strength = min(1.0, max(0.0, confidence * closeness * freshness_multiplier))
    reference = min(
        selected,
        key=lambda item: (
            sum(abs(item.projected_representative_price - other.projected_representative_price) for other in selected),
            item.projected_family_id,
        ),
    )
    return _make_cluster_with_asset(
        selected=selected,
        ids=ids,
        decision_timestamp=decision_timestamp,
        normalization_context=normalization_context,
        asset=asset,
        model_version=model_version,
        config_version=config_version,
        mtf_config_hash=mtf_config_hash,
        reference=reference,
        level_dispersion=level_dispersion,
        slope_dispersion=slope_dispersion,
        overlap=overlap,
        confluence_strength=confluence_strength,
        is_confluence=is_confluence,
        freshness_summary=freshness_summary,
    )


def _make_cluster_with_asset(
    *,
    selected: tuple[ProjectedMTFFamily, ...],
    ids: tuple[str, ...],
    decision_timestamp: datetime,
    normalization_context: MTFNormalizationContext,
    asset: str,
    model_version: str,
    config_version: str,
    mtf_config_hash: str,
    reference: ProjectedMTFFamily,
    level_dispersion: float | None,
    slope_dispersion: float | None,
    overlap: float | None,
    confluence_strength: float | None,
    is_confluence: bool,
    freshness_summary: str,
) -> MTFCluster:
    timeframes = tuple(sorted({item.source_timeframe for item in selected}, key=_timeframe_key))
    prices = [item.projected_representative_price for item in selected]
    reason_codes = tuple(sorted({"complete_linkage_v1", "confluence" if is_confluence else "singleton_or_subthreshold"}))
    payload = {
        "asset": asset, "decision_timestamp": decision_timestamp, "role": selected[0].source_family_role.value,
        "projected_family_ids": ids, "source_timeframes": timeframes,
        "reference_projected_family_id": reference.projected_family_id, "timeframe_count": len(timeframes),
        "family_count": len(selected), "minimum_projected_price": min(prices), "maximum_projected_price": max(prices),
        "span_atr": (max(prices) - min(prices)) / normalization_context.atr,
        "representative_level_dispersion_atr": level_dispersion, "normalized_slope_dispersion": slope_dispersion,
        "corridor_overlap_ratio": overlap, "confluence_strength": confluence_strength, "is_confluence": is_confluence,
        "freshness_summary": freshness_summary, "model_version": model_version, "config_version": config_version,
        "resolved_config_hash": mtf_config_hash, "reason_codes": reason_codes,
    }
    return MTFCluster(cluster_id=deterministic_id("mtf-cluster", payload), **payload)
