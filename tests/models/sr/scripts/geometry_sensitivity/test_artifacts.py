from __future__ import annotations

import json
import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import canonical_json, deterministic_hash
from libs.models.sr.scripts.geometry_sensitivity.artifacts import (
    publish_evaluation_bundle,
    validate_evaluation_bundle,
)


def test_study_bundle_round_trip_recomputes_all_candidates(tmp_path, study, geometry_config, repo_root):
    bundle_id, path = publish_evaluation_bundle(study, output_root=tmp_path, config=geometry_config)
    assert path.name == bundle_id
    validated = validate_evaluation_bundle(path, config=geometry_config, repo_root=repo_root, implementation_commit="a" * 40)
    assert validated.to_payload() == study.to_payload()


def test_fully_rehashed_decision_tampering_is_rejected(tmp_path, study, geometry_config, repo_root):
    bundle_id, path = publish_evaluation_bundle(study, output_root=tmp_path, config=geometry_config)
    payload = json.loads((path / "study.json").read_text(encoding="utf-8"))
    payload["disposition"] = "SELECT_GLOBAL_CHALLENGER"
    payload["selected_candidate_id"] = payload["baseline_candidate_id"]
    identity = dict(payload)
    identity.pop("study_id")
    payload["study_id"] = deterministic_hash(identity)
    study_bytes = (canonical_json(payload) + "\n").encode("utf-8")
    (path / "study.json").write_bytes(study_bytes)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    semantic = manifest["bundle_id_semantic_payload"]
    semantic["disposition"] = payload["disposition"]
    semantic["selected_candidate_id"] = payload["selected_candidate_id"]
    semantic["study_id"] = payload["study_id"]
    semantic["members"][0]["sha256"] = __import__("hashlib").sha256(study_bytes).hexdigest()
    semantic["members"][0]["byte_length"] = len(study_bytes)
    new_bundle_id = deterministic_hash(semantic)
    manifest["bundle_id"] = new_bundle_id
    manifest["bundle_id_semantic_payload"] = semantic
    (path / "manifest.json").write_bytes((canonical_json(manifest) + "\n").encode("utf-8"))
    new_path = path.parent / new_bundle_id
    path.rename(new_path)
    with pytest.raises(ContractValidationError):
        validate_evaluation_bundle(new_path, config=geometry_config, repo_root=repo_root, implementation_commit="a" * 40)
