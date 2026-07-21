"""MTF identity, semantic validation, and JSON serialization."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Mapping

from ..domain.identity import canonical_json, deterministic_id
from ..domain.validation import ContractValidationError
from .clustering import _build_clusters
from .contracts import (
    MTFCluster,
    MTFGeometrySnapshot,
    MTFNormalizationContext,
    MTFPolicyAudit,
    MTFRelation,
    MTFSourceSnapshotAudit,
    MTFSourceSnapshotReference,
    MTFSourceStatus,
    ProjectedMTFFamily,
    ProjectedMTFMember,
)
from .freshness import _source_audit
from .projection import _project_families
from .relations import _build_relations

def compute_mtf_snapshot_id(snapshot: MTFGeometrySnapshot) -> str:
    """Compute the content-addressed ID without accepting caller-controlled state."""

    return deterministic_id("mtf-geometry-snapshot", snapshot.identity_payload())


def _mtf_snapshot_identity_payload(
    *,
    asset: str,
    decision_timestamp: datetime,
    normalization_context: MTFNormalizationContext,
    policy_audit: MTFPolicyAudit,
    source_snapshot_audits: tuple[MTFSourceSnapshotAudit, ...],
    source_snapshots: tuple[MTFSourceSnapshotReference, ...],
    source_statuses: tuple[MTFSourceStatus, ...],
    projected_families: tuple[ProjectedMTFFamily, ...],
    projected_members: tuple[ProjectedMTFMember, ...],
    relations: tuple[MTFRelation, ...],
    clusters: tuple[MTFCluster, ...],
    model_version: str,
    config_version: str,
    resolved_config_hash: str,
    diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "asset": asset,
        "decision_timestamp": decision_timestamp,
        "normalization_context": normalization_context.to_dict(),
        "policy_audit": policy_audit.to_dict(),
        "source_snapshot_audits": tuple(item.to_dict() for item in source_snapshot_audits),
        "source_snapshots": tuple(item.to_dict() for item in source_snapshots),
        "source_statuses": tuple(item.to_dict() for item in source_statuses),
        "projected_families": tuple(item.to_dict() for item in projected_families),
        "projected_members": tuple(item.to_dict() for item in projected_members),
        "relations": tuple(item.to_dict() for item in relations),
        "clusters": tuple(item.to_dict() for item in clusters),
        "model_version": model_version,
        "config_version": config_version,
        "resolved_config_hash": resolved_config_hash,
        "diagnostics": diagnostics,
    }


def _validate_mtf_snapshot_semantics(snapshot: MTFGeometrySnapshot) -> None:
    """Rebuild all derived Phase-H evidence from persisted source audits and policy."""

    from .composition import _mtf_diagnostics

    policy = snapshot.policy_audit
    expected_references, expected_statuses = _source_audit(
        source_snapshot_audits=snapshot.source_snapshot_audits,
        decision_timestamp=snapshot.decision_timestamp,
        policy=policy,
    )
    if snapshot.source_snapshots != expected_references:
        raise ContractValidationError("MTF source references do not match canonical source audits")
    if snapshot.source_statuses != expected_statuses:
        raise ContractValidationError("MTF source statuses do not match canonical source audits")
    expected_families, expected_members, representative_geometries = _project_families(
        source_snapshot_audits=snapshot.source_snapshot_audits,
        source_references=expected_references,
        decision_timestamp=snapshot.decision_timestamp,
        normalization_context=snapshot.normalization_context,
    )
    if snapshot.projected_families != expected_families:
        raise ContractValidationError("projected MTF families do not match canonical source audits")
    if snapshot.projected_members != expected_members:
        raise ContractValidationError("projected MTF members do not match canonical source audits")
    expected_relations = _build_relations(
        families=expected_families,
        geometries=representative_geometries,
        decision_timestamp=snapshot.decision_timestamp,
        normalization_context=snapshot.normalization_context,
        policy=policy,
    )
    if snapshot.relations != expected_relations:
        raise ContractValidationError("MTF relations do not match projected evidence and policy")
    expected_clusters = _build_clusters(
        families=expected_families,
        relations=expected_relations,
        decision_timestamp=snapshot.decision_timestamp,
        normalization_context=snapshot.normalization_context,
        policy=policy,
        asset=policy.asset,
        model_version=policy.model_version,
        config_version=policy.config_version,
        mtf_config_hash=policy.mtf_config_hash,
    )
    if snapshot.clusters != expected_clusters:
        raise ContractValidationError("MTF clusters do not match complete-linkage policy evidence")
    expected_diagnostics = _mtf_diagnostics(
        policy=policy,
        source_statuses=expected_statuses,
        projected_families=expected_families,
        projected_members=expected_members,
        relations=expected_relations,
        clusters=expected_clusters,
    )
    if dict(snapshot.diagnostics) != expected_diagnostics:
        raise ContractValidationError("MTF diagnostics do not match persisted typed evidence")
def serialize_mtf_snapshot(snapshot: MTFGeometrySnapshot) -> str:
    if not isinstance(snapshot, MTFGeometrySnapshot):
        raise ContractValidationError("MTF snapshot serialization requires MTFGeometrySnapshot")
    return canonical_json(snapshot.to_dict())


def deserialize_mtf_snapshot(payload: str) -> MTFGeometrySnapshot:
    if not isinstance(payload, str):
        raise ContractValidationError("MTF snapshot payload must be JSON text")
    try:
        return MTFGeometrySnapshot.from_dict(json.loads(payload))
    except ContractValidationError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractValidationError("invalid MTF snapshot JSON payload") from exc
