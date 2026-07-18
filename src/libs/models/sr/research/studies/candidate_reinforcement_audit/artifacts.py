"""Deterministic V1.12 audit publication and fail-closed validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash
from libs.models.sr.research.artifacts.canonical_json import (
    canonical_json_bytes,
    sha256_hex,
)
from libs.models.sr.research.artifacts.manifest import (
    member_metadata,
    validate_member_metadata,
)
from libs.models.sr.research.artifacts.publisher import publish_immutable_directory
from libs.models.sr.research.artifacts.validator import load_strict_json
from libs.models.sr.research.artifacts.path_safety import (
    reject_symlink_components,
    require_regular_file,
)

from .config import CandidateAuditConfig
from .contracts import CandidateReinforcementAudit, validate_audit_payload


_MEMBERS = frozenset({"manifest.json", "audit.json"})
_STAGE = "candidate_reinforcement_audit_development"


def _bytes(payload: Any) -> bytes:
    return canonical_json_bytes(payload)


def _sha(data: bytes) -> str:
    return sha256_hex(data)


def _member(name: str, data: bytes) -> dict[str, Any]:
    return member_metadata(name, data)


def _atomic_publish(path: Path, files: dict[str, bytes]) -> None:
    publish_immutable_directory(path, files, description="V1.12 artifact")


def load_json(path: str | Path) -> Any:
    return load_strict_json(
        path,
        description="V1.12 JSON artifact",
        value_description="V1.12 artifact",
        require_regular=False,
    )


def _semantic(audit: CandidateReinforcementAudit, config: CandidateAuditConfig, member: dict[str, Any]) -> dict[str, Any]:
    if audit.config_hash != config.config_hash:
        raise ContractValidationError("audit/config identity mismatch")
    return {
        "schema_version": "1.0",
        "stage": _STAGE,
        "implementation_commit": audit.implementation_commit,
        "config_hash": config.config_hash,
        "config": config.to_payload(),
        "v11_bundle_id": audit.v11_bundle_id,
        "v11_study_id": audit.v11_study_id,
        "v19_bundle_id": audit.v19_bundle_id,
        "v19_study_id": audit.v19_study_id,
        "v10_bundle_id": audit.v10_bundle_id,
        "v10_audit_id": audit.v10_audit_id,
        "source_bundle_id": audit.source_bundle_id,
        "upstream_source_bundle_id": audit.upstream_source_bundle_id,
        "source_id": audit.source_id,
        "bars_sha256": audit.bars_sha256,
        "audit_id": audit.audit_id,
        "disposition": audit.decision.disposition.value,
        "member": member,
    }


def _validate_manifest(path: Path) -> dict[str, Any]:
    if not path.is_dir() or path.is_symlink() or {item.name for item in path.iterdir()} != _MEMBERS:
        raise ContractValidationError("V1.12 artifact member set mismatch")
    manifest_path = path / "manifest.json"
    audit_path = path / "audit.json"
    require_regular_file(manifest_path, description="V1.12 artifact member")
    require_regular_file(audit_path, description="V1.12 artifact member")
    manifest = load_json(manifest_path)
    if type(manifest) is not dict:
        raise ContractValidationError("V1.12 manifest must be a mapping")
    semantic = manifest.get("bundle_id_semantic_payload")
    bundle_id = manifest.get("bundle_id")
    if type(semantic) is not dict or type(bundle_id) is not str or deterministic_hash(semantic) != bundle_id or path.name != bundle_id:
        raise ContractValidationError("V1.12 bundle identity mismatch")
    expected_semantic = {
        "schema_version", "stage", "implementation_commit", "config_hash", "config",
        "v11_bundle_id", "v11_study_id", "v19_bundle_id", "v19_study_id",
        "v10_bundle_id", "v10_audit_id", "source_bundle_id", "upstream_source_bundle_id",
        "source_id", "bars_sha256", "audit_id", "disposition", "member",
    }
    if set(semantic) != expected_semantic or set(manifest) != expected_semantic | {"bundle_id", "bundle_id_semantic_payload"}:
        raise ContractValidationError("V1.12 manifest schema mismatch")
    for key, value in semantic.items():
        if manifest.get(key) != value:
            raise ContractValidationError(f"V1.12 manifest semantic field mismatch: {key}")
    member = validate_member_metadata(
        semantic["member"],
        expected_name="audit.json",
        description="V1.12 audit member",
    )
    try:
        data = audit_path.read_bytes()
    except OSError as exc:
        raise ContractValidationError("V1.12 audit member cannot be read") from exc
    if _sha(data) != member["sha256"] or len(data) != member["byte_length"]:
        raise ContractValidationError("V1.12 audit member hash mismatch")
    return manifest


def publish_audit_bundle(
    audit: CandidateReinforcementAudit,
    *,
    config: CandidateAuditConfig,
    output_root: str | Path,
) -> tuple[str, Path]:
    if type(audit) is not CandidateReinforcementAudit or type(config) is not CandidateAuditConfig:
        raise ContractValidationError("V1.12 publication requires typed audit/config")
    audit_bytes = _bytes(audit.to_payload())
    member = _member("audit.json", audit_bytes)
    semantic = _semantic(audit, config, member)
    bundle_id = deterministic_hash(semantic)
    manifest = {**semantic, "bundle_id": bundle_id, "bundle_id_semantic_payload": semantic}
    path = Path(output_root) / "audit" / bundle_id
    _atomic_publish(path, {"manifest.json": _bytes(manifest), "audit.json": audit_bytes})
    return bundle_id, path


def validate_audit_bundle(
    path: str | Path,
    *,
    config: CandidateAuditConfig,
    repo_root: str | Path,
    implementation_commit: str | None = None,
    expected_bundle_id: str | None = None,
) -> CandidateReinforcementAudit:
    reject_symlink_components(Path(path), description="V1.12 artifact")
    bundle_path = Path(path).resolve()
    manifest = _validate_manifest(bundle_path)
    semantic = manifest["bundle_id_semantic_payload"]
    if expected_bundle_id is not None and manifest["bundle_id"] != expected_bundle_id:
        raise ContractValidationError("V1.12 bundle ID does not match requested identity")
    if semantic["config_hash"] != config.config_hash or semantic["config"] != config.to_payload():
        raise ContractValidationError("V1.12 manifest config binding mismatch")
    commit = semantic["implementation_commit"] if implementation_commit is None else implementation_commit
    if semantic["implementation_commit"] != commit:
        raise ContractValidationError("V1.12 implementation identity mismatch")
    from .runner import compute_audit

    recomputed = compute_audit(config, repo_root=repo_root, implementation_commit=commit)
    validate_audit_payload(load_json(bundle_path / "audit.json"), recomputed)
    expected_member = _member("audit.json", _bytes(recomputed.to_payload()))
    expected_semantic = _semantic(recomputed, config, expected_member)
    if semantic != expected_semantic or manifest["bundle_id"] != deterministic_hash(expected_semantic):
        raise ContractValidationError("V1.12 manifest does not match semantic recomputation")
    return recomputed


load_candidate_audit_bundle = validate_audit_bundle
publish_candidate_audit_bundle = publish_audit_bundle


__all__ = [
    "load_candidate_audit_bundle", "load_json", "publish_audit_bundle",
    "publish_candidate_audit_bundle", "validate_audit_bundle",
]
