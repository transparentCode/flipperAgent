"""Deterministic V1.10 audit publication and semantic validation."""

from __future__ import annotations

from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import canonical_json, deterministic_hash

from .config import ContextAuditConfig
from .contracts import AuditResult, validate_audit_payload


_MEMBERS = frozenset({"manifest.json", "audit.json", "chart_payload.json"})
_STAGE = "context_semantics_audit_development"


def _bytes(payload: Any) -> bytes:
    return (canonical_json(payload) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _member(name: str, data: bytes) -> dict[str, Any]:
    return {"name": name, "sha256": _sha(data), "byte_length": len(data)}


def _atomic_publish(path: Path, files: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_dir() or path.is_symlink() or {item.name for item in path.iterdir()} != set(files):
            raise ContractValidationError("existing V1.10 artifact path has unexpected members")
        for name, data in files.items():
            if (path / name).read_bytes() != data:
                raise ContractValidationError("existing V1.10 artifact bytes differ")
        return
    temporary = Path(tempfile.mkdtemp(prefix=f".{path.name}.", dir=path.parent))
    try:
        for name, data in files.items():
            (temporary / name).write_bytes(data)
        os.replace(temporary, path)
    except OSError as exc:
        raise ContractValidationError("atomic V1.10 artifact publication failed") from exc
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
        raise ContractValidationError(f"non-finite artifact value at {path}")
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
        raise ContractValidationError(f"invalid V1.10 JSON artifact: {path}") from exc
    _finite(payload)
    return payload


def _semantic(
    audit: AuditResult,
    chart_unbound: dict[str, Any],
    config: ContextAuditConfig,
    basis_members: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    if audit.config_hash != config.config_hash:
        raise ContractValidationError("audit/config identity mismatch")
    return {
        "schema_version": "1.0",
        "stage": _STAGE,
        "created_by": "sr_v1.10_context_semantics_audit",
        "implementation_commit": audit.implementation_commit,
        "config_hash": config.config_hash,
        "config": config.to_payload(),
        "trial_name": config.trial_name,
        "venue": config.venue,
        "asset": config.asset,
        "timeframe": config.timeframe,
        "purpose": config.purpose,
        "audit_status": audit.audit_status,
        "audit_id": audit.audit_id,
        "v19_bundle_id": audit.v19_bundle_id,
        "v19_study_id": audit.v19_study_id,
        "v19_disposition": audit.v19_disposition,
        "source_bundle_id": audit.source_bundle_id,
        "source_id": audit.source_id,
        "trace_id": audit.trace_id,
        "case_count": len(audit.cases),
        "comparison_count": sum(item.comparison is not None for item in audit.cases),
        "chart_payload_identity_hash": deterministic_hash({key: value for key, value in chart_unbound.items() if key != "bundle_id"}),
        "bundle_id_basis_members": list(basis_members),
    }


def _validate_member_metadata(value: Any, *, name: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {"name", "sha256", "byte_length"}:
        raise ContractValidationError(f"V1.10 {name} member metadata is malformed")
    if value["name"] not in {"audit.json", "chart_payload.json"} or type(value["sha256"]) is not str or len(value["sha256"]) != 64 or any(char not in "0123456789abcdef" for char in value["sha256"]) or type(value["byte_length"]) is not int or value["byte_length"] < 0:
        raise ContractValidationError(f"V1.10 {name} member metadata types are invalid")
    return value


def _validate_manifest(path: Path) -> dict[str, Any]:
    if not path.is_dir() or path.is_symlink() or {item.name for item in path.iterdir()} != _MEMBERS:
        raise ContractValidationError("V1.10 artifact member set mismatch")
    manifest = load_json(path / "manifest.json")
    if type(manifest) is not dict:
        raise ContractValidationError("V1.10 manifest must be a mapping")
    semantic = manifest.get("bundle_id_semantic_payload")
    bundle_id = manifest.get("bundle_id")
    if type(semantic) is not dict or type(bundle_id) is not str or deterministic_hash(semantic) != bundle_id or path.name != bundle_id:
        raise ContractValidationError("V1.10 bundle identity mismatch")
    expected_semantic = {
        "schema_version", "stage", "created_by", "implementation_commit", "config_hash", "config",
        "trial_name", "venue", "asset", "timeframe", "purpose", "audit_status", "audit_id",
        "v19_bundle_id", "v19_study_id", "v19_disposition", "source_bundle_id", "source_id",
        "trace_id", "case_count", "comparison_count", "chart_payload_identity_hash",
        "bundle_id_basis_members",
    }
    expected_manifest = expected_semantic | {"bundle_id", "bundle_id_semantic_payload", "members"}
    if set(semantic) != expected_semantic or set(manifest) != expected_manifest:
        raise ContractValidationError("V1.10 manifest schema mismatch")
    for key, value in semantic.items():
        if key != "bundle_id_basis_members" and manifest.get(key) != value:
            raise ContractValidationError(f"V1.10 manifest semantic field mismatch: {key}")
    basis = semantic["bundle_id_basis_members"]
    members = manifest["members"]
    if type(basis) is not list or len(basis) != 2 or type(members) is not list or len(members) != 2:
        raise ContractValidationError("V1.10 manifest member metadata count is invalid")
    basis_members = tuple(_validate_member_metadata(value, name="basis") for value in basis)
    final_members = tuple(_validate_member_metadata(value, name="final") for value in members)
    if {item["name"] for item in basis_members} != {"audit.json", "chart_payload.json"} or {item["name"] for item in final_members} != {"audit.json", "chart_payload.json"}:
        raise ContractValidationError("V1.10 manifest member names are invalid")
    if next(item for item in basis_members if item["name"] == "audit.json") != next(item for item in final_members if item["name"] == "audit.json"):
        raise ContractValidationError("V1.10 audit member identity changed after binding")
    for member in final_members:
        data = (path / member["name"]).read_bytes()
        if _sha(data) != member["sha256"] or len(data) != member["byte_length"]:
            raise ContractValidationError(f"V1.10 member hash mismatch: {member['name']}")
    return manifest


def publish_audit_bundle(
    audit: AuditResult,
    chart_unbound: dict[str, Any],
    *,
    config: ContextAuditConfig,
    output_root: str | Path,
) -> tuple[str, Path]:
    if type(audit) is not AuditResult or type(config) is not ContextAuditConfig or type(chart_unbound) is not dict:
        raise ContractValidationError("V1.10 publication requires typed audit/config and chart mapping")
    if chart_unbound.get("bundle_id") is not None:
        raise ContractValidationError("V1.10 chart payload must be unbound before publication")
    audit_bytes = _bytes(audit.to_payload())
    unbound_chart_bytes = _bytes(chart_unbound)
    basis_members = (_member("audit.json", audit_bytes), _member("chart_payload.json", unbound_chart_bytes))
    semantic = _semantic(audit, chart_unbound, config, basis_members)
    bundle_id = deterministic_hash(semantic)
    chart = {**chart_unbound, "bundle_id": bundle_id}
    chart_bytes = _bytes(chart)
    members = (_member("audit.json", audit_bytes), _member("chart_payload.json", chart_bytes))
    manifest = {
        **semantic,
        "bundle_id": bundle_id,
        "members": list(members),
        "bundle_id_semantic_payload": semantic,
    }
    path = Path(output_root) / bundle_id
    _atomic_publish(path, {"manifest.json": _bytes(manifest), "audit.json": audit_bytes, "chart_payload.json": chart_bytes})
    return bundle_id, path


def validate_audit_bundle(
    path: str | Path,
    *,
    config: ContextAuditConfig,
    repo_root: str | Path,
    implementation_commit: str | None = None,
    expected_bundle_id: str | None = None,
) -> AuditResult:
    bundle_path = Path(path).resolve()
    manifest = _validate_manifest(bundle_path)
    semantic = manifest["bundle_id_semantic_payload"]
    if expected_bundle_id is not None and manifest["bundle_id"] != expected_bundle_id:
        raise ContractValidationError("V1.10 bundle ID does not match requested identity")
    if semantic["config_hash"] != config.config_hash or semantic["config"] != config.to_payload():
        raise ContractValidationError("V1.10 manifest config binding mismatch")
    commit = semantic["implementation_commit"] if implementation_commit is None else implementation_commit
    if semantic["implementation_commit"] != commit:
        raise ContractValidationError("V1.10 implementation identity mismatch")
    from .runner import compute_audit

    recomputed, chart_unbound = compute_audit(config, repo_root=repo_root, implementation_commit=commit)
    audit_payload = load_json(bundle_path / "audit.json")
    validate_audit_payload(audit_payload, recomputed)
    expected_chart = {**chart_unbound, "bundle_id": manifest["bundle_id"]}
    chart_payload = load_json(bundle_path / "chart_payload.json")
    if chart_payload != expected_chart:
        raise ContractValidationError("V1.10 chart payload does not match semantic recomputation")
    if chart_payload.get("bundle_id") != manifest["bundle_id"]:
        raise ContractValidationError("V1.10 chart bundle binding mismatch")
    audit_bytes = _bytes(recomputed.to_payload())
    basis_members = (_member("audit.json", audit_bytes), _member("chart_payload.json", _bytes(chart_unbound)))
    expected_semantic = _semantic(recomputed, chart_unbound, config, basis_members)
    if semantic != expected_semantic or manifest["bundle_id"] != deterministic_hash(expected_semantic):
        raise ContractValidationError("V1.10 manifest does not match semantic recomputation")
    expected_members = (_member("audit.json", audit_bytes), _member("chart_payload.json", _bytes(expected_chart)))
    if tuple(manifest["members"]) != expected_members:
        raise ContractValidationError("V1.10 final member metadata does not match recomputation")
    return recomputed


load_audit_bundle = validate_audit_bundle


__all__ = ["load_audit_bundle", "load_json", "publish_audit_bundle", "validate_audit_bundle"]
