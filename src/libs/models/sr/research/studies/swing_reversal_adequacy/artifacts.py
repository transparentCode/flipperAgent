"""Immutable publication and semantic validation for SR-V2.2 evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash
from libs.models.sr.research.artifacts.canonical_json import canonical_json_bytes
from libs.models.sr.research.artifacts.manifest import (
    member_metadata,
    validate_member_metadata,
)
from libs.models.sr.research.artifacts.path_safety import (
    reject_symlink_components,
    require_regular_file,
)
from libs.models.sr.research.artifacts.publisher import publish_immutable_directory
from libs.models.sr.research.artifacts.validator import load_strict_json

from .config import SwingReversalAdequacyConfig
from .contracts import SwingReversalStudy


_SCHEMA_VERSION = "1.0"


def _bytes(payload: Any) -> bytes:
    return canonical_json_bytes(payload)


def _semantic(
    study: SwingReversalStudy,
    config: SwingReversalAdequacyConfig,
    *,
    study_member: dict[str, Any],
    cases_member: dict[str, Any],
) -> dict[str, Any]:
    if study.config_hash != config.config_hash:
        raise ContractValidationError("V2.2 study/config identity mismatch")
    return {
        "schema_version": _SCHEMA_VERSION,
        "stage": config.artifact.stage,
        "implementation_commit": study.implementation_commit,
        "config_hash": config.config_hash,
        "config": config.to_payload(),
        "source_bundle_id": study.source_bundle_id,
        "source_capsule_bundle_id": study.source_capsule_bundle_id,
        "source_id": study.source_id,
        "study_id": study.study_id,
        "disposition": study.decision.disposition.value,
        "members": [study_member, cases_member],
    }


def publish_study_bundle(
    study: SwingReversalStudy,
    *,
    config: SwingReversalAdequacyConfig,
    output_root: str | Path,
) -> tuple[str, Path]:
    if (
        type(study) is not SwingReversalStudy
        or type(config) is not SwingReversalAdequacyConfig
    ):
        raise ContractValidationError("V2.2 publication requires typed study/config")
    study_bytes, cases_bytes = (
        _bytes(study.to_payload()),
        _bytes(study.casebook_payload()),
    )
    semantic = _semantic(
        study,
        config,
        study_member=member_metadata("study.json", study_bytes),
        cases_member=member_metadata("cases.json", cases_bytes),
    )
    bundle_id = deterministic_hash(semantic)
    manifest = {
        **semantic,
        "bundle_id": bundle_id,
        "bundle_id_semantic_payload": semantic,
    }
    destination = Path(output_root) / "evaluation" / bundle_id
    publish_immutable_directory(
        destination,
        {
            "manifest.json": _bytes(manifest),
            "study.json": study_bytes,
            "cases.json": cases_bytes,
        },
        description="V2.2 swing-reversal evidence",
    )
    return bundle_id, destination


def _validate_manifest(
    path: Path, config: SwingReversalAdequacyConfig
) -> dict[str, Any]:
    if (
        not path.is_dir()
        or path.is_symlink()
        or {item.name for item in path.iterdir()} != set(config.artifact.members)
    ):
        raise ContractValidationError("V2.2 artifact member set mismatch")
    members = tuple(path / name for name in config.artifact.members)
    for member in members:
        require_regular_file(member, description="V2.2 artifact member")
    manifest = load_strict_json(
        path / "manifest.json",
        description="V2.2 manifest",
        value_description="V2.2 artifact",
        require_regular=False,
    )
    expected_keys = {
        "schema_version",
        "stage",
        "implementation_commit",
        "config_hash",
        "config",
        "source_bundle_id",
        "source_capsule_bundle_id",
        "source_id",
        "study_id",
        "disposition",
        "members",
    }
    semantic, bundle_id = (
        manifest.get("bundle_id_semantic_payload") if type(manifest) is dict else None,
        manifest.get("bundle_id") if type(manifest) is dict else None,
    )
    if (
        type(semantic) is not dict
        or type(bundle_id) is not str
        or set(semantic) != expected_keys
        or set(manifest) != expected_keys | {"bundle_id", "bundle_id_semantic_payload"}
        or deterministic_hash(semantic) != bundle_id
        or path.name != bundle_id
    ):
        raise ContractValidationError("V2.2 manifest identity/schema mismatch")
    if (
        any(manifest.get(key) != value for key, value in semantic.items())
        or semantic["config_hash"] != config.config_hash
        or semantic["config"] != config.to_payload()
    ):
        raise ContractValidationError("V2.2 manifest config/semantic binding mismatch")
    raw_members = semantic["members"]
    if type(raw_members) is not list or len(raw_members) != 2:
        raise ContractValidationError("V2.2 manifest member metadata is invalid")
    metadata: dict[str, dict[str, Any]] = {}
    for item in raw_members:
        if (
            type(item) is not dict
            or type(item.get("name")) is not str
            or item["name"] in metadata
        ):
            raise ContractValidationError("V2.2 manifest member metadata is invalid")
        metadata[item["name"]] = validate_member_metadata(
            item, expected_name=item["name"], description="V2.2 evidence member"
        )
    if set(metadata) != {"study.json", "cases.json"}:
        raise ContractValidationError("V2.2 manifest member names are invalid")
    for name, item in metadata.items():
        if member_metadata(name, (path / name).read_bytes()) != item:
            raise ContractValidationError(f"V2.2 artifact member hash mismatch: {name}")
    return manifest


def validate_study_bundle(
    path: str | Path,
    *,
    config: SwingReversalAdequacyConfig,
    repo_root: str | Path,
    implementation_commit: str | None = None,
    expected_bundle_id: str | None = None,
) -> SwingReversalStudy:
    if type(config) is not SwingReversalAdequacyConfig:
        raise ContractValidationError("V2.2 validation requires typed configuration")
    reject_symlink_components(Path(path), description="V2.2 artifact")
    bundle_path = Path(path).resolve()
    manifest = _validate_manifest(bundle_path, config)
    semantic = manifest["bundle_id_semantic_payload"]
    if expected_bundle_id is not None and manifest["bundle_id"] != expected_bundle_id:
        raise ContractValidationError(
            "V2.2 bundle ID does not match requested identity"
        )
    commit = (
        semantic["implementation_commit"]
        if implementation_commit is None
        else implementation_commit
    )
    if semantic["implementation_commit"] != commit:
        raise ContractValidationError("V2.2 implementation identity mismatch")
    from .runner import compute_swing_reversal_study

    recomputed = compute_swing_reversal_study(
        config, repo_root=repo_root, implementation_commit=commit
    )
    study_payload = load_strict_json(
        bundle_path / "study.json",
        description="V2.2 study",
        value_description="V2.2 artifact",
        require_regular=False,
    )
    cases_payload = load_strict_json(
        bundle_path / "cases.json",
        description="V2.2 cases",
        value_description="V2.2 artifact",
        require_regular=False,
    )
    if (
        study_payload != recomputed.to_payload()
        or cases_payload != recomputed.casebook_payload()
    ):
        raise ContractValidationError(
            "V2.2 evidence does not match semantic recomputation"
        )
    expected = _semantic(
        recomputed,
        config,
        study_member=member_metadata("study.json", _bytes(recomputed.to_payload())),
        cases_member=member_metadata(
            "cases.json", _bytes(recomputed.casebook_payload())
        ),
    )
    if semantic != expected or manifest["bundle_id"] != deterministic_hash(expected):
        raise ContractValidationError(
            "V2.2 manifest does not match semantic recomputation"
        )
    return recomputed


__all__ = ["publish_study_bundle", "validate_study_bundle"]
