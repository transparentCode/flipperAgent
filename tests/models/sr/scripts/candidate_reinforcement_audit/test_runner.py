from __future__ import annotations

from types import SimpleNamespace

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.scripts.candidate_reinforcement_audit import runner


def test_repository_commit_is_full_sha():
    commit = runner.repository_commit(".")
    assert len(commit) >= 40
    assert all(character in "0123456789abcdef" for character in commit)


def test_repository_commit_preserves_v112_error_context(monkeypatch):
    def fail(repo_root):
        raise ContractValidationError("cannot determine repository commit")

    monkeypatch.setattr(runner, "_repository_commit", fail)

    with pytest.raises(ContractValidationError, match="cannot determine V1.12 implementation commit"):
        runner.repository_commit(".")


def test_root_path_preserves_v112_escape_error(tmp_path):
    with pytest.raises(ContractValidationError, match="inputs.path escaped repository root"):
        runner._root_path(tmp_path, "../escape.json", field_name="inputs.path")


def test_compute_audit_does_not_import_provider_or_create_source(monkeypatch, candidate_config):
    forbidden = {"build_source_capsules", "load_frozen_source"}
    seen: set[str] = set()

    def fail(*args, **kwargs):
        seen.add("called")
        raise AssertionError("forbidden source preparation path")

    import libs.models.sr.scripts.cohort_readiness.source as source

    for name in forbidden:
        if hasattr(source, name):
            monkeypatch.setattr(source, name, fail)

    frozen = SimpleNamespace(
        model_bars=(),
        resolved_sr=object(),
        canonical_replay=object(),
        validated_v11=SimpleNamespace(v10_audit=SimpleNamespace(cases=())),
    )
    monkeypatch.setattr(runner, "_validate_inputs", lambda *args, **kwargs: frozen)
    sentinel = object()
    monkeypatch.setattr(runner, "build_audit", lambda *args, **kwargs: sentinel)

    assert runner.compute_audit(candidate_config, repo_root=".", implementation_commit="a" * 40) is sentinel
    assert not seen
