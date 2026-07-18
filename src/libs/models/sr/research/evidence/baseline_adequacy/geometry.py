"""Explicit immutable V1.8 frozen-evidence boundary for V1.9 consumers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash
from libs.models.sr.research.artifacts.validator import load_strict_json
from libs.models.sr.research.config.identities import ContentIdentity
from libs.models.sr.research.source.frozen import read_verified_frozen_file


@dataclass(frozen=True)
class FrozenGeometryConfig:
    config_hash: str


@dataclass(frozen=True)
class FrozenGeometryStudy:
    study_id: str
    disposition: str
    selected_candidate_id: str | None
    baseline_candidate_id: str


def load_frozen_geometry_study(
    path: str | Path,
    *,
    config_hash: str,
    implementation_commit: str,
    bundle_id: str,
) -> tuple[FrozenGeometryConfig, FrozenGeometryStudy]:
    """Validate immutable V1.8 member bytes needed by V1.9 evidence only."""
    bundle = Path(path)
    if not bundle.is_dir() or bundle.is_symlink():
        raise ContractValidationError("V1.8 study bundle is missing")
    manifest_path = bundle / "manifest.json"
    study_path = bundle / "study.json"
    if any(not item.is_file() or item.is_symlink() for item in (manifest_path, study_path)):
        raise ContractValidationError("V1.8 study bundle members are invalid")
    manifest = load_strict_json(manifest_path, description="V1.8 manifest")
    semantic = manifest.get("bundle_id_semantic_payload")
    if (
        type(semantic) is not dict
        or manifest.get("bundle_id") != bundle_id
        or deterministic_hash(semantic) != bundle_id
    ):
        raise ContractValidationError("V1.8 bundle ID does not match requested identity")
    if (
        semantic.get("config_hash") != config_hash
        or semantic.get("implementation_commit") != implementation_commit
    ):
        raise ContractValidationError("V1.8 manifest config or implementation binding mismatch")
    if any(manifest.get(key) != value for key, value in semantic.items()):
        raise ContractValidationError("V1.8 manifest top-level binding mismatch")
    members = semantic.get("members")
    if (
        type(members) is not list
        or len(members) != 1
        or type(members[0]) is not dict
        or set(members[0]) != {"name", "sha256", "byte_length"}
        or members[0].get("name") != "study.json"
    ):
        raise ContractValidationError("V1.8 manifest members are invalid")
    member = members[0]
    try:
        raw = read_verified_frozen_file(
            study_path,
            identity=ContentIdentity(
                sha256=member["sha256"],
                byte_length=member["byte_length"],
            ),
            description="V1.8 study member",
        )
    except ContractValidationError as exc:
        raise ContractValidationError("V1.8 study member hash mismatch") from exc
    study = load_strict_json(study_path, description="V1.8 study")
    if not raw:
        raise ContractValidationError("V1.8 study member hash mismatch")
    if study.get("study_id") != semantic.get("study_id") or study.get("disposition") != semantic.get("disposition"):
        raise ContractValidationError("V1.8 study member identity mismatch")
    baseline_candidate_id = study.get("baseline_candidate_id")
    if type(baseline_candidate_id) is not str:
        raise ContractValidationError("V1.8 baseline candidate identity is invalid")
    selected = study.get("selected_candidate_id")
    if selected is not None and type(selected) is not str:
        raise ContractValidationError("V1.8 selected candidate identity is invalid")
    return FrozenGeometryConfig(config_hash=config_hash), FrozenGeometryStudy(
        study_id=study["study_id"],
        disposition=study["disposition"],
        selected_candidate_id=selected,
        baseline_candidate_id=baseline_candidate_id,
    )
