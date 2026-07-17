"""Deterministic V1.12 audit publication and fail-closed validation."""

from __future__ import annotations

from hashlib import sha256
import json
import math
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import canonical_json, deterministic_hash

from .config import CandidateAuditConfig
from .contracts import CandidateReinforcementAudit, validate_audit_payload


_MEMBERS = frozenset({"manifest.json", "audit.json"})
_STAGE = "candidate_reinforcement_audit_development"


def _bytes(payload: Any) -> bytes:
    return (canonical_json(payload) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _member(name: str, data: bytes) -> dict[str, Any]:
    return {"name": name, "sha256": _sha(data), "byte_length": len(data)}


def _require_regular_member(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise ContractValidationError(f"V1.12 artifact member cannot be read: {path}") from exc
    if not stat.S_ISREG(mode):
        raise ContractValidationError(f"V1.12 artifact member must be a regular file: {path}")


def _atomic_publish(path: Path, files: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_dir() or path.is_symlink() or {item.name for item in path.iterdir()} != set(files):
            raise ContractValidationError("existing V1.12 artifact path has unexpected members")
        for name, data in files.items():
            member_path = path / name
            _require_regular_member(member_path)
            try:
                current = member_path.read_bytes()
            except OSError as exc:
                raise ContractValidationError("existing V1.12 artifact member cannot be read") from exc
            if current != data:
                raise ContractValidationError("existing V1.12 artifact bytes differ")
        return
    temporary = Path(tempfile.mkdtemp(prefix=f".{path.name}.", dir=path.parent))
    try:
        for name, data in files.items():
            (temporary / name).write_bytes(data)
        os.replace(temporary, path)
    except OSError as exc:
        raise ContractValidationError("atomic V1.12 artifact publication failed") from exc
    finally:
        if temporary.exists():
            for item in temporary.iterdir():
                item.unlink()
            temporary.rmdir()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {value}")


def _finite(value: Any, *, path: str = "json") -> None:
    if type(value) is float and not math.isfinite(value):
        raise ContractValidationError(f"non-finite V1.12 artifact value at {path}")
    if type(value) is dict:
        for key, item in value.items():
            _finite(item, path=f"{path}.{key}")
    elif type(value) is list:
        for index, item in enumerate(value):
            _finite(item, path=f"{path}[{index}]")


def load_json(path: str | Path) -> Any:
    try:
        payload = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid V1.12 JSON artifact: {path}") from exc
    _finite(payload)
    return payload


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
    _require_regular_member(manifest_path)
    _require_regular_member(audit_path)
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
    member = semantic["member"]
    if type(member) is not dict or set(member) != {"name", "sha256", "byte_length"} or member.get("name") != "audit.json" or type(member.get("sha256")) is not str or len(member["sha256"]) != 64 or type(member.get("byte_length")) is not int or member["byte_length"] < 0:
        raise ContractValidationError("V1.12 audit member metadata is malformed")
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
