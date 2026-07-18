"""Deterministic V1.9 study publication and semantic validation."""

from __future__ import annotations

from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.domain.identity import canonical_json, deterministic_hash

from .contracts import BaselineAdequacyConfig, BaselineAdequacyStudy


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
            raise ContractValidationError("existing V1.9 artifact path has unexpected members")
        for name, data in files.items():
            if (path / name).read_bytes() != data:
                raise ContractValidationError("existing V1.9 artifact bytes differ")
        return
    temporary = Path(tempfile.mkdtemp(prefix=f".{path.name}.", dir=path.parent))
    try:
        for name, data in files.items():
            (temporary / name).write_bytes(data)
        os.replace(temporary, path)
    except OSError as exc:
        raise ContractValidationError("atomic V1.9 artifact publication failed") from exc
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


def _finite(value: Any, *, path: str = "json") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractValidationError(f"non-finite artifact value at {path}")
    if isinstance(value, dict):
        for key, item in value.items():
            _finite(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _finite(item, path=f"{path}[{index}]")


def load_json(path: str | Path) -> Any:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise ContractValidationError(f"invalid V1.9 JSON artifact: {path}") from exc
    _finite(payload)
    return payload


def _semantic(study: BaselineAdequacyStudy, config: BaselineAdequacyConfig, members: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    if study.config_hash != config.config_hash:
        raise ContractValidationError("study/config identity mismatch")
    return {
        "schema_version": "1.0",
        "stage": "baseline_adequacy_development",
        "created_by": "sr_v1.9_baseline_adequacy",
        "implementation_commit": study.implementation_commit,
        "config_hash": config.config_hash,
        "config": config.to_payload(),
        "source_bundle_id": study.source_bundle_id,
        "source_id": study.source_id,
        "v17_config_hash": study.v17_config_hash,
        "v17_evaluation_bundle_id": study.v17_evaluation_bundle_id,
        "v17_evaluation_id": study.v17_evaluation_id,
        "v18_config_hash": study.v18_config_hash,
        "v18_study_bundle_id": study.v18_study_bundle_id,
        "v18_study_id": study.v18_study_id,
        "frozen_sr_config_hash": study.frozen_sr_config_hash,
        "frozen_input_hash": study.frozen_input_hash,
        "baseline_candidate_id": study.baseline_candidate_id,
        "disposition": study.decision.disposition.value,
        "study_id": study.study_id,
        "members": list(members),
    }


def publish_evaluation_bundle(study: BaselineAdequacyStudy, *, output_root: str | Path, config: BaselineAdequacyConfig) -> tuple[str, Path]:
    if type(study) is not BaselineAdequacyStudy or type(config) is not BaselineAdequacyConfig:
        raise ContractValidationError("V1.9 publication requires typed study/config")
    study_bytes = _bytes(study.to_payload())
    members = (_member("study.json", study_bytes),)
    semantic = _semantic(study, config, members)
    bundle_id = deterministic_hash(semantic)
    if deterministic_hash(semantic) != bundle_id:
        raise ContractValidationError("V1.9 bundle identity construction failed")
    manifest = {**semantic, "bundle_id": bundle_id, "bundle_id_semantic_payload": semantic}
    path = Path(output_root) / "evaluation" / bundle_id
    _atomic_publish(path, {"manifest.json": _bytes(manifest), "study.json": study_bytes})
    return bundle_id, path


def _validate_manifest(path: Path) -> dict[str, Any]:
    expected_members = {"manifest.json", "study.json"}
    if not path.is_dir() or path.is_symlink() or {item.name for item in path.iterdir()} != expected_members:
        raise ContractValidationError("V1.9 artifact member set mismatch")
    manifest = load_json(path / "manifest.json")
    if type(manifest) is not dict:
        raise ContractValidationError("V1.9 manifest must be a mapping")
    semantic = manifest.get("bundle_id_semantic_payload")
    bundle_id = manifest.get("bundle_id")
    if type(semantic) is not dict or type(bundle_id) is not str or deterministic_hash(semantic) != bundle_id or path.name != bundle_id:
        raise ContractValidationError("V1.9 bundle identity mismatch")
    expected_semantic = {
        "schema_version", "stage", "created_by", "implementation_commit", "config_hash", "config", "source_bundle_id", "source_id", "v17_config_hash", "v17_evaluation_bundle_id", "v17_evaluation_id", "v18_config_hash", "v18_study_bundle_id", "v18_study_id", "frozen_sr_config_hash", "frozen_input_hash", "baseline_candidate_id", "disposition", "study_id", "members",
    }
    expected_manifest = expected_semantic | {"bundle_id", "bundle_id_semantic_payload"}
    if set(semantic) != expected_semantic or set(manifest) != expected_manifest:
        raise ContractValidationError("V1.9 manifest schema mismatch")
    for key, value in semantic.items():
        if manifest.get(key) != value:
            raise ContractValidationError(f"V1.9 manifest top-level field mismatch: {key}")
    members = semantic["members"]
    if type(members) is not list or len(members) != 1 or type(members[0]) is not dict or set(members[0]) != {"name", "sha256", "byte_length"} or members[0]["name"] != "study.json":
        raise ContractValidationError("V1.9 member metadata is malformed")
    member = members[0]
    if type(member["sha256"]) is not str or len(member["sha256"]) != 64 or type(member["byte_length"]) is not int or member["byte_length"] < 0:
        raise ContractValidationError("V1.9 member metadata types are invalid")
    data = (path / "study.json").read_bytes()
    if _sha(data) != member["sha256"] or len(data) != member["byte_length"]:
        raise ContractValidationError("V1.9 study member hash mismatch")
    return manifest


def validate_evaluation_bundle(
    path: str | Path,
    *,
    config: BaselineAdequacyConfig,
    repo_root: str | Path,
    implementation_commit: str | None = None,
    expected_bundle_id: str | None = None,
) -> BaselineAdequacyStudy:
    """Recompute frozen inputs, controls, metrics, and decision before accepting bytes."""
    bundle_path = Path(path)
    manifest = _validate_manifest(bundle_path)
    semantic = manifest["bundle_id_semantic_payload"]
    if expected_bundle_id is not None and manifest["bundle_id"] != expected_bundle_id:
        raise ContractValidationError("V1.9 bundle ID does not match requested identity")
    if semantic["config_hash"] != config.config_hash or semantic["config"] != config.to_payload():
        raise ContractValidationError("V1.9 manifest config binding mismatch")
    if implementation_commit is None:
        implementation_commit = semantic["implementation_commit"]
    if semantic["implementation_commit"] != implementation_commit:
        raise ContractValidationError("V1.9 implementation identity mismatch")
    from .runner import compute_study

    recomputed = compute_study(config, repo_root=repo_root, implementation_commit=implementation_commit)
    payload = load_json(bundle_path / "study.json")
    if payload != recomputed.to_payload():
        raise ContractValidationError("V1.9 study member does not match semantic recomputation")
    expected_semantic = _semantic(recomputed, config, tuple(semantic["members"]))
    if semantic != expected_semantic or manifest["bundle_id"] != deterministic_hash(expected_semantic):
        raise ContractValidationError("V1.9 manifest does not match recomputed study")
    return recomputed


load_evaluation_bundle = validate_evaluation_bundle
publish_study_bundle = publish_evaluation_bundle
validate_study_bundle = validate_evaluation_bundle


__all__ = ["load_evaluation_bundle", "load_json", "publish_evaluation_bundle", "publish_study_bundle", "validate_evaluation_bundle", "validate_study_bundle"]
