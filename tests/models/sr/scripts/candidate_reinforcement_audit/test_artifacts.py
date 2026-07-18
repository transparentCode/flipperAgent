from __future__ import annotations

from hashlib import sha256

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import canonical_json, deterministic_hash
from libs.models.sr.research.studies.candidate_reinforcement_audit import runner
from libs.models.sr.scripts.candidate_reinforcement_audit.artifacts import (
    load_json,
    publish_audit_bundle,
    validate_audit_bundle,
)


def member(name: str, data: bytes) -> dict[str, object]:
    return {"name": name, "sha256": sha256(data).hexdigest(), "byte_length": len(data)}


def test_bundle_is_deterministic_and_semantically_revalidated(tmp_path, monkeypatch, candidate_config, synthetic_audit):
    bundle_id, path = publish_audit_bundle(synthetic_audit, config=candidate_config, output_root=tmp_path)
    second_id, second_path = publish_audit_bundle(synthetic_audit, config=candidate_config, output_root=tmp_path)
    assert (bundle_id, path) == (second_id, second_path)
    monkeypatch.setattr(runner, "compute_audit", lambda *args, **kwargs: synthetic_audit)
    validated = validate_audit_bundle(path, config=candidate_config, repo_root=tmp_path, implementation_commit=synthetic_audit.implementation_commit)
    assert validated.to_payload() == synthetic_audit.to_payload()


def test_duplicate_json_keys_fail_closed(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"a": 1, "a": 2}', encoding="utf-8")
    with pytest.raises(ContractValidationError):
        load_json(path)


def test_rehashed_audit_tampering_is_rejected(tmp_path, monkeypatch, candidate_config, synthetic_audit):
    _, original = publish_audit_bundle(synthetic_audit, config=candidate_config, output_root=tmp_path)
    payload = load_json(original / "audit.json")
    payload["decision"]["reason"] = "tampered"
    audit_bytes = (canonical_json(payload) + "\n").encode("utf-8")
    (original / "audit.json").write_bytes(audit_bytes)
    manifest = load_json(original / "manifest.json")
    semantic = dict(manifest["bundle_id_semantic_payload"])
    audit_member = member("audit.json", audit_bytes)
    semantic["member"] = audit_member
    manifest["member"] = audit_member
    manifest["bundle_id_semantic_payload"] = semantic
    new_bundle_id = deterministic_hash(semantic)
    manifest["bundle_id"] = new_bundle_id
    (original / "manifest.json").write_bytes((canonical_json(manifest) + "\n").encode("utf-8"))
    tampered = original.parent / new_bundle_id
    original.rename(tampered)
    monkeypatch.setattr(runner, "compute_audit", lambda *args, **kwargs: synthetic_audit)
    with pytest.raises(ContractValidationError):
        validate_audit_bundle(tampered, config=candidate_config, repo_root=tmp_path, implementation_commit=synthetic_audit.implementation_commit)


def test_wrong_implementation_binding_is_rejected(tmp_path, candidate_config, synthetic_audit):
    _, path = publish_audit_bundle(synthetic_audit, config=candidate_config, output_root=tmp_path)
    with pytest.raises(ContractValidationError):
        validate_audit_bundle(path, config=candidate_config, repo_root=tmp_path, implementation_commit="b" * 40)


@pytest.mark.parametrize("member_name", ("manifest.json", "audit.json"))
def test_member_symlink_is_rejected_during_validation(
    tmp_path, monkeypatch, candidate_config, synthetic_audit, member_name
):
    _, path = publish_audit_bundle(synthetic_audit, config=candidate_config, output_root=tmp_path)
    member_path = path / member_name
    target = tmp_path / f"{member_name}.target"
    target.write_bytes(member_path.read_bytes())
    member_path.unlink()
    member_path.symlink_to(target)

    monkeypatch.setattr(runner, "compute_audit", lambda *args, **kwargs: synthetic_audit)
    with pytest.raises(ContractValidationError, match="regular file"):
        validate_audit_bundle(
            path,
            config=candidate_config,
            repo_root=tmp_path,
            implementation_commit=synthetic_audit.implementation_commit,
        )


@pytest.mark.parametrize("member_name", ("manifest.json", "audit.json"))
def test_existing_bundle_publication_rejects_member_symlink(
    tmp_path, candidate_config, synthetic_audit, member_name
):
    _, path = publish_audit_bundle(synthetic_audit, config=candidate_config, output_root=tmp_path)
    member_path = path / member_name
    target = tmp_path / f"{member_name}.publish-target"
    target.write_bytes(member_path.read_bytes())
    member_path.unlink()
    member_path.symlink_to(target)

    with pytest.raises(ContractValidationError, match="regular file"):
        publish_audit_bundle(synthetic_audit, config=candidate_config, output_root=tmp_path)


@pytest.mark.parametrize("member_name", ("manifest.json", "audit.json"))
def test_non_regular_member_is_rejected_during_validation(
    tmp_path, candidate_config, synthetic_audit, member_name
):
    _, path = publish_audit_bundle(synthetic_audit, config=candidate_config, output_root=tmp_path)
    member_path = path / member_name
    member_path.unlink()
    member_path.mkdir()

    with pytest.raises(ContractValidationError, match="regular file"):
        from libs.models.sr.scripts.candidate_reinforcement_audit.artifacts import _validate_manifest

        _validate_manifest(path)


def test_bundle_directory_symlink_is_rejected_by_public_validation(
    tmp_path, monkeypatch, candidate_config, synthetic_audit
):
    _, path = publish_audit_bundle(synthetic_audit, config=candidate_config, output_root=tmp_path)
    alias = tmp_path / "bundle-alias"
    alias.symlink_to(path, target_is_directory=True)

    monkeypatch.setattr(runner, "compute_audit", lambda *args, **kwargs: synthetic_audit)
    with pytest.raises(ContractValidationError, match="contains symlink"):
        validate_audit_bundle(
            alias,
            config=candidate_config,
            repo_root=tmp_path,
            implementation_commit=synthetic_audit.implementation_commit,
        )


def test_symlinked_parent_directory_is_rejected_by_public_validation(
    tmp_path, monkeypatch, candidate_config, synthetic_audit
):
    real_root = tmp_path / "real-root"
    _, path = publish_audit_bundle(synthetic_audit, config=candidate_config, output_root=real_root)
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(real_root, target_is_directory=True)
    aliased_path = linked_root / "audit" / path.name

    monkeypatch.setattr(runner, "compute_audit", lambda *args, **kwargs: synthetic_audit)
    with pytest.raises(ContractValidationError, match="contains symlink"):
        validate_audit_bundle(
            aliased_path,
            config=candidate_config,
            repo_root=tmp_path,
            implementation_commit=synthetic_audit.implementation_commit,
        )
