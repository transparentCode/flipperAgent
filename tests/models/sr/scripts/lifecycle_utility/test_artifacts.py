from __future__ import annotations

from hashlib import sha256

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import canonical_json, deterministic_hash
from libs.models.sr.scripts.lifecycle_utility import runner
from libs.models.sr.scripts.lifecycle_utility.artifacts import (
    load_json,
    publish_lifecycle_bundle,
    validate_lifecycle_bundle,
)


def member(name: str, data: bytes) -> dict[str, object]:
    return {"name": name, "sha256": sha256(data).hexdigest(), "byte_length": len(data)}


def test_bundle_is_deterministic_and_semantically_revalidated(tmp_path, monkeypatch, lifecycle_config, synthetic_study):
    study = synthetic_study()
    bundle_id, path = publish_lifecycle_bundle(study, config=lifecycle_config, output_root=tmp_path)
    second_id, second_path = publish_lifecycle_bundle(study, config=lifecycle_config, output_root=tmp_path)
    assert (bundle_id, path) == (second_id, second_path)
    monkeypatch.setattr(runner, "compute_study", lambda *args, **kwargs: study)
    validated = validate_lifecycle_bundle(path, config=lifecycle_config, repo_root=tmp_path, implementation_commit=study.implementation_commit)
    assert validated.to_payload() == study.to_payload()


def test_sparse_fold_study_reconciles_comparable_records(lifecycle_config, synthetic_study):
    study = synthetic_study(counts=(5, 5, 5, 1))
    assert study.aggregate.comparable_fold_count == 3
    assert study.aggregate.compared_count == 15
    assert sum(item.compared for item in study.outcomes) == 16
    assert study.decision.disposition.value == "INSUFFICIENT_EVIDENCE"


def test_rehashed_study_tampering_is_rejected(tmp_path, monkeypatch, lifecycle_config, synthetic_study):
    study = synthetic_study()
    _, original = publish_lifecycle_bundle(study, config=lifecycle_config, output_root=tmp_path)
    payload = load_json(original / "study.json")
    payload["study_id"] = deterministic_hash({"tampered": True})
    study_bytes = (canonical_json(payload) + "\n").encode("utf-8")
    (original / "study.json").write_bytes(study_bytes)
    manifest = load_json(original / "manifest.json")
    semantic = dict(manifest["bundle_id_semantic_payload"])
    study_member = member("study.json", study_bytes)
    semantic["member"] = study_member
    manifest["member"] = study_member
    manifest["bundle_id_semantic_payload"] = semantic
    new_bundle_id = deterministic_hash(semantic)
    manifest["bundle_id"] = new_bundle_id
    (original / "manifest.json").write_bytes((canonical_json(manifest) + "\n").encode("utf-8"))
    tampered = original.parent / new_bundle_id
    original.rename(tampered)
    monkeypatch.setattr(runner, "compute_study", lambda *args, **kwargs: study)
    with pytest.raises(ContractValidationError):
        validate_lifecycle_bundle(tampered, config=lifecycle_config, repo_root=tmp_path, implementation_commit=study.implementation_commit)


def test_duplicate_json_keys_fail_closed(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"a": 1, "a": 2}', encoding="utf-8")
    with pytest.raises(ContractValidationError):
        load_json(path)


def test_manifest_implementation_override_is_explicitly_checked(tmp_path, monkeypatch, lifecycle_config, synthetic_study):
    study = synthetic_study()
    _, path = publish_lifecycle_bundle(study, config=lifecycle_config, output_root=tmp_path)
    monkeypatch.setattr(runner, "compute_study", lambda *args, **kwargs: study)
    with pytest.raises(ContractValidationError):
        validate_lifecycle_bundle(path, config=lifecycle_config, repo_root=tmp_path, implementation_commit="b" * 40)
