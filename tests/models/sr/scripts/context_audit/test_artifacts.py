from __future__ import annotations

import json

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import canonical_json, deterministic_hash
from libs.models.sr.scripts.context_audit.artifacts import (
    publish_audit_bundle,
    validate_audit_bundle,
)


def test_three_member_round_trip_and_manifest_commit_default(context_result, context_config, repo_root, tmp_path, monkeypatch):
    audit, chart = context_result
    bundle_id, path = publish_audit_bundle(audit, chart, config=context_config, output_root=tmp_path)
    assert path.name == bundle_id
    assert {item.name for item in path.iterdir()} == {"manifest.json", "audit.json", "chart_payload.json"}
    import libs.models.sr.scripts.context_audit.runner as runner
    monkeypatch.setattr(runner, "compute_audit", lambda *args, **kwargs: (audit, chart))
    loaded = validate_audit_bundle(path, config=context_config, repo_root=repo_root)
    assert loaded.audit_id == audit.audit_id


def test_explicit_implementation_mismatch_is_rejected(context_result, context_config, repo_root, tmp_path, monkeypatch):
    audit, chart = context_result
    _, path = publish_audit_bundle(audit, chart, config=context_config, output_root=tmp_path)
    import libs.models.sr.scripts.context_audit.runner as runner
    monkeypatch.setattr(runner, "compute_audit", lambda *args, **kwargs: (audit, chart))
    with pytest.raises(ContractValidationError):
        validate_audit_bundle(path, config=context_config, repo_root=repo_root, implementation_commit="0" * 40)


def test_duplicate_manifest_keys_are_rejected(context_result, context_config, repo_root, tmp_path):
    audit, chart = context_result
    _, path = publish_audit_bundle(audit, chart, config=context_config, output_root=tmp_path)
    manifest = (path / "manifest.json").read_text(encoding="utf-8").rstrip()
    (path / "manifest.json").write_text(manifest[:-1] + ',"duplicate":1,"duplicate":2}\n', encoding="utf-8")
    with pytest.raises(ContractValidationError, match="invalid V1.10 JSON"):
        validate_audit_bundle(path, config=context_config, repo_root=repo_root)


def test_rehashed_chart_tampering_is_rejected(context_result, context_config, repo_root, tmp_path, monkeypatch):
    audit, chart = context_result
    bundle_id, path = publish_audit_bundle(audit, chart, config=context_config, output_root=tmp_path)
    payload = json.loads((path / "chart_payload.json").read_text(encoding="utf-8"))
    payload["casebook"]["notice"] = "tampered"
    chart_bytes = (canonical_json(payload) + "\n").encode("utf-8")
    (path / "chart_payload.json").write_bytes(chart_bytes)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    member = next(item for item in manifest["members"] if item["name"] == "chart_payload.json")
    member["sha256"] = __import__("hashlib").sha256(chart_bytes).hexdigest()
    member["byte_length"] = len(chart_bytes)
    semantic = manifest["bundle_id_semantic_payload"]
    new_bundle_id = deterministic_hash(semantic)
    manifest["bundle_id"] = new_bundle_id
    manifest["bundle_id_semantic_payload"] = semantic
    (path / "manifest.json").write_bytes((canonical_json(manifest) + "\n").encode("utf-8"))
    import libs.models.sr.scripts.context_audit.runner as runner
    monkeypatch.setattr(runner, "compute_audit", lambda *args, **kwargs: (audit, chart))
    with pytest.raises(ContractValidationError):
        validate_audit_bundle(path, config=context_config, repo_root=repo_root)
