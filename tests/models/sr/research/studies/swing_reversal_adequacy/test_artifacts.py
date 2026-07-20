from dataclasses import replace
import json
from pathlib import Path
import shutil

import pytest

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash
from libs.models.sr.research.artifacts.canonical_json import canonical_json_bytes
from libs.models.sr.research.artifacts.manifest import member_metadata

from libs.models.sr.research.studies.swing_reversal_adequacy.artifacts import (
    publish_study_bundle,
    validate_study_bundle,
)
from libs.models.sr.research.studies.swing_reversal_adequacy.config import (
    ArtifactProtocol,
    load_swing_reversal_adequacy_config,
)
from libs.models.sr.research.studies.swing_reversal_adequacy.runner import (
    compute_swing_reversal_study,
)


_ROOT = Path(__file__).resolve().parents[6]
_CONFIG = _ROOT / "configs/sr_trials/sr_v2_2_taousdt_1d_swing_reversal_adequacy.yaml"


def _bundle(tmp_path: Path) -> tuple[object, str, Path, object]:
    config = load_swing_reversal_adequacy_config(str(_CONFIG))
    config = replace(
        config,
        artifact=ArtifactProtocol(
            "unused", config.artifact.stage, config.artifact.members
        ),
    )
    study = compute_swing_reversal_study(
        config, repo_root=_ROOT, implementation_commit="b" * 40
    )
    bundle_id, path = publish_study_bundle(study, config=config, output_root=tmp_path)
    return config, bundle_id, path, study


def test_bundle_recomputes_semantics(tmp_path: Path) -> None:
    config, bundle_id, path, study = _bundle(tmp_path)
    assert (
        validate_study_bundle(
            path, config=config, repo_root=_ROOT, expected_bundle_id=bundle_id
        ).study_id
        == study.study_id
    )


def test_rehashed_semantic_tampering_is_rejected(tmp_path: Path) -> None:
    config, _, path, _ = _bundle(tmp_path)
    study_payload = json.loads((path / "study.json").read_text())
    study_payload["decision"]["disposition"] = "SWING_REVERSAL_BEATS_NAIVE_NULL"
    study_payload["decision"]["reason"] = "all utility gates passed after readiness"
    identity = dict(study_payload)
    identity.pop("study_id")
    study_payload["study_id"] = deterministic_hash(identity)
    study_bytes = canonical_json_bytes(study_payload)
    manifest = json.loads((path / "manifest.json").read_text())
    semantic = manifest["bundle_id_semantic_payload"]
    semantic["study_id"] = study_payload["study_id"]
    semantic["disposition"] = study_payload["decision"]["disposition"]
    semantic["members"] = [
        member_metadata("study.json", study_bytes),
        semantic["members"][1],
    ]
    bundle_id = deterministic_hash(semantic)
    tampered = path.parent / bundle_id
    path.rename(tampered)
    manifest = {
        **semantic,
        "bundle_id": bundle_id,
        "bundle_id_semantic_payload": semantic,
    }
    (tampered / "study.json").write_bytes(study_bytes)
    (tampered / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    with pytest.raises(ContractValidationError, match="semantic recomputation"):
        validate_study_bundle(tampered, config=config, repo_root=_ROOT)


def test_member_and_parent_symlinks_are_rejected(tmp_path: Path) -> None:
    config, _, path, _ = _bundle(tmp_path / "original")
    member_copy = tmp_path / "member"
    shutil.copytree(path, member_copy)
    target = tmp_path / "study-target.json"
    target.write_bytes((member_copy / "study.json").read_bytes())
    (member_copy / "study.json").unlink()
    (member_copy / "study.json").symlink_to(target)
    with pytest.raises(ContractValidationError):
        validate_study_bundle(member_copy, config=config, repo_root=_ROOT)

    parent = tmp_path / "parent"
    parent.symlink_to(path.parent, target_is_directory=True)
    with pytest.raises(ContractValidationError):
        validate_study_bundle(parent / path.name, config=config, repo_root=_ROOT)
