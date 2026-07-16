from __future__ import annotations

import json
from hashlib import sha256

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import canonical_json, deterministic_hash
from libs.models.sr.scripts.baseline_adequacy.artifacts import publish_evaluation_bundle, validate_evaluation_bundle


def test_round_trip_and_recomputed_identity(adequacy_study, adequacy_config, repo_root, tmp_path):
    bundle_id, path = publish_evaluation_bundle(adequacy_study, output_root=tmp_path, config=adequacy_config)
    loaded = validate_evaluation_bundle(path, config=adequacy_config, repo_root=repo_root, implementation_commit=adequacy_study.implementation_commit, expected_bundle_id=bundle_id)
    assert loaded.study_id == adequacy_study.study_id


def test_rehashed_study_tampering_is_rejected(adequacy_study, adequacy_config, repo_root, tmp_path):
    bundle_id, path = publish_evaluation_bundle(adequacy_study, output_root=tmp_path, config=adequacy_config)
    study = json.loads((path / "study.json").read_text(encoding="utf-8"))
    study["control_outcomes"].pop()
    study_bytes = (canonical_json(study) + "\n").encode("utf-8")
    (path / "study.json").write_bytes(study_bytes)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    member = manifest["bundle_id_semantic_payload"]["members"][0]
    member["sha256"] = sha256(study_bytes).hexdigest()
    member["byte_length"] = len(study_bytes)
    semantic = manifest["bundle_id_semantic_payload"]
    manifest["bundle_id"] = deterministic_hash(semantic)
    (path / "manifest.json").write_bytes((canonical_json(manifest) + "\n").encode("utf-8"))
    with pytest.raises(ContractValidationError):
        validate_evaluation_bundle(path, config=adequacy_config, repo_root=repo_root, implementation_commit=adequacy_study.implementation_commit)
