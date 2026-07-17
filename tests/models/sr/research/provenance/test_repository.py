from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.research.provenance import repository


def test_repository_commit_returns_exact_current_head():
    root = Path.cwd()
    expected = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
    ).strip()

    assert repository.repository_commit(root) == expected


@pytest.mark.parametrize("root_kind", ("missing", "file"))
def test_resolve_repository_root_rejects_missing_or_non_directory(tmp_path, root_kind):
    root = tmp_path / root_kind
    if root_kind == "file":
        root.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ContractValidationError, match="repository root must be an existing directory"):
        repository.resolve_repository_root(root)


def test_repository_commit_translates_git_command_failure(tmp_path, monkeypatch):
    root = tmp_path / "repository"
    root.mkdir()

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(repository.subprocess, "check_output", fail)

    with pytest.raises(ContractValidationError, match="cannot determine repository commit"):
        repository.repository_commit(root)


def test_repository_commit_rejects_malformed_git_output(monkeypatch):
    monkeypatch.setattr(repository, "resolve_repository_root", lambda _: Path.cwd())
    monkeypatch.setattr(repository.subprocess, "check_output", lambda *args, **kwargs: "not-a-sha\n")

    with pytest.raises(ContractValidationError, match="cannot determine repository commit"):
        repository.repository_commit(".")


def test_resolve_repository_path_keeps_safe_existing_and_future_paths_inside_root(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    existing = root / "evidence.json"
    existing.write_text("evidence", encoding="utf-8")

    assert repository.resolve_repository_path(root, "evidence.json", field_name="input") == existing
    assert repository.resolve_repository_path(
        root,
        "future/nested/evidence.json",
        field_name="input",
    ) == root / "future" / "nested" / "evidence.json"


def test_resolve_repository_path_rejects_absolute_and_parent_escape(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()

    for relative in (str(tmp_path / "absolute.json"), "../escape.json"):
        with pytest.raises(ContractValidationError, match="input escaped repository root"):
            repository.resolve_repository_path(root, relative, field_name="input")


def test_resolve_repository_path_rejects_symlink_escape(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ContractValidationError, match="input escaped repository root"):
        repository.resolve_repository_path(root, "link/escaped.json", field_name="input")
