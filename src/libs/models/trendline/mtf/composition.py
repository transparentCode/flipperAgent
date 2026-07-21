"""Validate and orchestrate downstream multi-timeframe composition."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from ..configuration.contracts import ResolvedTrendlineFamilyConfig
from ..domain.identity import deterministic_id
from ..domain.snapshots import TrendlineFamilySnapshot
from ..domain.validation import ContractValidationError, require_utc
from .clustering import _build_clusters
from .contracts import (
    MTFCluster,
    MTFFreshnessState,
    MTFGeometrySnapshot,
    MTFNormalizationContext,
    MTFPolicyAudit,
    MTFRelation,
    MTFSourceSnapshotAudit,
    MTFSourceStatus,
    ProjectedMTFFamily,
    ProjectedMTFMember,
    _timeframe_key,
    _validate_confirmed_phase_g_source,
    _validate_policy_source_timeframes,
    timeframe_duration_seconds,
)
from .freshness import _source_audit
from .projection import _project_families
from .relations import _build_relations
from .serialization import _mtf_snapshot_identity_payload

def _mtf_diagnostics(
    *,
    policy: MTFPolicyAudit,
    source_statuses: tuple[MTFSourceStatus, ...],
    projected_families: tuple[ProjectedMTFFamily, ...],
    projected_members: tuple[ProjectedMTFMember, ...],
    relations: tuple[MTFRelation, ...],
    clusters: tuple[MTFCluster, ...],
) -> dict[str, Any]:
    return {
        "mtf_enabled": True,
        "normalization_policy": policy.normalization_policy,
        "mtf_config_hash": policy.mtf_config_hash,
        "configured_source_timeframes": policy.source_timeframes,
        "source_timeframe_count": sum(status.freshness_state is not MTFFreshnessState.MISSING for status in source_statuses),
        "missing_source_timeframes": tuple(status.source_timeframe for status in source_statuses if status.freshness_state is MTFFreshnessState.MISSING),
        "stale_excluded_source_timeframes": tuple(status.source_timeframe for status in source_statuses if status.freshness_state is MTFFreshnessState.STALE_EXCLUDED),
        "projected_family_count": len(projected_families),
        "projected_member_count": len(projected_members),
        "relation_count": len(relations),
        "cluster_count": len(clusters),
    }
def compose_mtf_snapshot(
    *,
    source_snapshots: Mapping[str, TrendlineFamilySnapshot],
    decision_timestamp: datetime,
    normalization_context: MTFNormalizationContext,
    config: ResolvedTrendlineFamilyConfig,
) -> MTFGeometrySnapshot:
    """Compose immutable Phase-G sources at one causal decision timestamp."""

    if not isinstance(config, ResolvedTrendlineFamilyConfig):
        raise ContractValidationError("MTF composition requires ResolvedTrendlineFamilyConfig")
    if not config.mtf.enabled:
        raise ContractValidationError("MTF composition requires mtf.enabled=True")
    if not isinstance(source_snapshots, Mapping):
        raise ContractValidationError("source_snapshots must be a timeframe mapping")
    if normalization_context.policy != config.mtf.normalization_policy:
        raise ContractValidationError("normalization context policy must match resolved MTF config")
    if normalization_context.asset != config.asset:
        raise ContractValidationError("normalization context asset must match resolved config")
    if normalization_context.decision_timeframe != config.timeframe:
        raise ContractValidationError("normalization context timeframe must match resolved config")
    decision_timestamp = require_utc(decision_timestamp, field_name="MTF decision_timestamp")
    policy_audit = MTFPolicyAudit.from_config(
        config=config,
        decision_timeframe=normalization_context.decision_timeframe,
    )
    normalized_sources = _validate_sources(
        source_snapshots=source_snapshots,
        decision_timestamp=decision_timestamp,
        policy=policy_audit,
    )
    source_snapshot_audits = tuple(
        MTFSourceSnapshotAudit.from_snapshot(snapshot)
        for _, snapshot in normalized_sources
    )
    source_references, source_statuses = _source_audit(
        source_snapshot_audits=source_snapshot_audits,
        decision_timestamp=decision_timestamp,
        policy=policy_audit,
    )
    projected_families, projected_members, representative_geometries = _project_families(
        source_snapshot_audits=source_snapshot_audits,
        source_references=source_references,
        decision_timestamp=decision_timestamp,
        normalization_context=normalization_context,
    )
    relations = _build_relations(
        families=projected_families,
        geometries=representative_geometries,
        decision_timestamp=decision_timestamp,
        normalization_context=normalization_context,
        policy=policy_audit,
    )
    clusters = _build_clusters(
        families=projected_families,
        relations=relations,
        decision_timestamp=decision_timestamp,
        normalization_context=normalization_context,
        policy=policy_audit,
        asset=config.asset,
        model_version=config.model_version,
        config_version=config.config_version,
        mtf_config_hash=config.mtf_config_hash,
    )
    diagnostics = _mtf_diagnostics(
        policy=policy_audit,
        source_statuses=source_statuses,
        projected_families=projected_families,
        projected_members=projected_members,
        relations=relations,
        clusters=clusters,
    )
    snapshot_id = deterministic_id(
        "mtf-geometry-snapshot",
        _mtf_snapshot_identity_payload(
            asset=config.asset,
            decision_timestamp=decision_timestamp,
            normalization_context=normalization_context,
            policy_audit=policy_audit,
            source_snapshot_audits=source_snapshot_audits,
            source_snapshots=source_references,
            source_statuses=source_statuses,
            projected_families=projected_families,
            projected_members=projected_members,
            relations=relations,
            clusters=clusters,
            model_version=config.model_version,
            config_version=config.config_version,
            resolved_config_hash=config.mtf_config_hash,
            diagnostics=diagnostics,
        ),
    )
    return MTFGeometrySnapshot(
        mtf_snapshot_id=snapshot_id,
        asset=config.asset,
        decision_timestamp=decision_timestamp,
        normalization_context=normalization_context,
        policy_audit=policy_audit,
        source_snapshot_audits=source_snapshot_audits,
        source_snapshots=source_references,
        source_statuses=source_statuses,
        projected_families=projected_families,
        projected_members=projected_members,
        relations=relations,
        clusters=clusters,
        model_version=config.model_version,
        config_version=config.config_version,
        resolved_config_hash=config.mtf_config_hash,
        diagnostics=diagnostics,
    )


def _validate_sources(
    *,
    source_snapshots: Mapping[str, TrendlineFamilySnapshot],
    decision_timestamp: datetime,
    policy: MTFPolicyAudit,
) -> tuple[tuple[str, TrendlineFamilySnapshot], ...]:
    pairs: list[tuple[str, TrendlineFamilySnapshot]] = []
    seen_timeframes: set[str] = set()
    for key, snapshot in source_snapshots.items():
        if not isinstance(key, str):
            raise ContractValidationError("source snapshot mapping keys must be timeframes")
        timeframe_duration_seconds(key)
        if not isinstance(snapshot, TrendlineFamilySnapshot):
            raise ContractValidationError("source snapshots must use TrendlineFamilySnapshot")
        if snapshot.timeframe != key:
            raise ContractValidationError("source snapshot mapping key must match snapshot timeframe")
        if key in seen_timeframes:
            raise ContractValidationError("duplicate source timeframe")
        seen_timeframes.add(key)
        if snapshot.asset != policy.asset:
            raise ContractValidationError("source snapshot asset mismatch")
        if snapshot.timestamp > decision_timestamp:
            raise ContractValidationError("future source snapshot cannot enter MTF composition")
        _validate_confirmed_phase_g_source(snapshot)
        pairs.append((key, snapshot))
    _validate_policy_source_timeframes(seen_timeframes, policy=policy)
    return tuple(sorted(pairs, key=lambda item: _timeframe_key(item[0])))
