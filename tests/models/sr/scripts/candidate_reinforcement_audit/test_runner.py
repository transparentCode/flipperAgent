from __future__ import annotations

from libs.models.sr.scripts.candidate_reinforcement_audit import runner


def test_repository_commit_is_full_sha():
    commit = runner.repository_commit(".")
    assert len(commit) >= 40
    assert all(character in "0123456789abcdef" for character in commit)


def test_run_audit_does_not_import_provider_or_create_source(monkeypatch):
    forbidden = {"build_source_capsules", "load_frozen_source"}
    seen: set[str] = set()

    def fail(*args, **kwargs):
        seen.add("called")
        raise AssertionError("forbidden source preparation path")

    import libs.models.sr.scripts.cohort_readiness.source as source

    for name in forbidden:
        if hasattr(source, name):
            monkeypatch.setattr(source, name, fail)
    assert not seen
