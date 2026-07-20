import os
from pathlib import Path

import pytest

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.research.studies.adaptive_context_calibration.artifacts import (
    canonical_json_bytes,
    load_source_bundle,
    publish_evaluation_bundle,
    publish_source_bundle,
    sha256_hex,
    validate_evaluation_bundle,
)
from libs.models.sr.research.studies.adaptive_context_calibration.runner import (
    compute_study,
)
from libs.models.sr.domain.identity import deterministic_hash


def test_source_bundle_publication_round_trips_and_rejects_tamper(tmp_path: Path, synthetic_source_bundle) -> None:
    bundle_id, path = publish_source_bundle(synthetic_source_bundle, output_root=tmp_path)
    assert bundle_id == synthetic_source_bundle.bundle_id
    loaded = load_source_bundle(path, expected_bundle_id=bundle_id)
    assert loaded.bundle_id == bundle_id
    original = (path / "TAOUSDT_12h.json").read_bytes()
    (path / "TAOUSDT_12h.json").write_bytes(original + b" ")
    with pytest.raises(ContractValidationError, match="hash mismatch"):
        load_source_bundle(path, expected_bundle_id=bundle_id)


def test_source_bundle_rejects_member_bundle_parent_symlinks_and_nonregular_files(
    tmp_path: Path, synthetic_source_bundle
) -> None:
    bundle_id, path = publish_source_bundle(synthetic_source_bundle, output_root=tmp_path / "members")
    target = tmp_path / "member-bytes.json"
    target.write_bytes((path / "TAOUSDT_12h.json").read_bytes())
    member = path / "TAOUSDT_12h.json"
    member.unlink()
    member.symlink_to(target)
    with pytest.raises(ContractValidationError, match="symlink"):
        load_source_bundle(path, expected_bundle_id=bundle_id)

    bundle_id, path = publish_source_bundle(synthetic_source_bundle, output_root=tmp_path / "nonregular")
    member = path / "TAOUSDT_12h.json"
    member.unlink()
    member.mkdir()
    with pytest.raises(ContractValidationError, match="regular file"):
        load_source_bundle(path, expected_bundle_id=bundle_id)

    bundle_id, path = publish_source_bundle(synthetic_source_bundle, output_root=tmp_path / "parent")
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(path.parent, target_is_directory=True)
    with pytest.raises(ContractValidationError, match="symlink"):
        load_source_bundle(linked_parent / path.name, expected_bundle_id=bundle_id)


def _published_evaluation(tmp_path: Path, config, synthetic_source_bundle):
    study = compute_study(
        config,
        source_bundle=synthetic_source_bundle,
        implementation_commit="60331170abbbb5e538a4a67fa3a970a137160758",
    )
    bundle_id, path = publish_evaluation_bundle(
        study,
        config=config,
        output_root=tmp_path,
    )
    return study, bundle_id, path


def test_evaluation_rejects_implementation_mismatch_and_member_symlink(
    tmp_path: Path, config, synthetic_source_bundle
) -> None:
    _, bundle_id, path = _published_evaluation(tmp_path, config, synthetic_source_bundle)
    with pytest.raises(ContractValidationError, match="implementation identity mismatch"):
        validate_evaluation_bundle(
            path,
            config=config,
            source_bundle=synthetic_source_bundle,
            implementation_commit="a" * 40,
            expected_bundle_id=bundle_id,
        )
    target = tmp_path / "study-bytes.json"
    target.write_bytes((path / "study.json").read_bytes())
    member = path / "study.json"
    member.unlink()
    member.symlink_to(target)
    with pytest.raises(ContractValidationError, match="symlink"):
        validate_evaluation_bundle(
            path,
            config=config,
            source_bundle=synthetic_source_bundle,
            expected_bundle_id=bundle_id,
        )


def test_rehashed_evaluation_semantic_tampering_fails_closed(
    tmp_path: Path, config, synthetic_source_bundle
) -> None:
    _, _, path = _published_evaluation(tmp_path, config, synthetic_source_bundle)
    from libs.models.sr.research.studies.adaptive_context_calibration.artifacts import (
        load_json,
    )

    study = load_json(path / "study.json")
    study["disposition"] = "ADAPTIVE_CONTEXT_SUPPORTED_FOR_SHADOW"
    study["study_id"] = deterministic_hash(
        {key: value for key, value in study.items() if key != "study_id"}
    )
    study_bytes = canonical_json_bytes(study)
    (path / "study.json").write_bytes(study_bytes)

    manifest = load_json(path / "manifest.json")
    semantic = manifest["bundle_id_semantic_payload"]
    semantic["study_id"] = study["study_id"]
    for member in semantic["members"]:
        if member["name"] == "study.json":
            member["sha256"] = sha256_hex(study_bytes)
            member["byte_length"] = len(study_bytes)
    bundle_id = deterministic_hash(semantic)
    manifest = {
        **semantic,
        "bundle_id": bundle_id,
        "bundle_id_semantic_payload": semantic,
    }
    replacement = path.parent / bundle_id
    os.rename(path, replacement)
    (replacement / "manifest.json").write_bytes(canonical_json_bytes(manifest))

    with pytest.raises(ContractValidationError, match="semantics"):
        validate_evaluation_bundle(
            replacement,
            config=config,
            source_bundle=synthetic_source_bundle,
            expected_bundle_id=bundle_id,
        )
