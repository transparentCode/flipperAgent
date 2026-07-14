"""Tests for change_detector utilities."""

from __future__ import annotations

from pathlib import Path

from conductor.change_detector import ValidationResult, git_diff_files, run_tests


def test_git_diff_files_returns_list(tmp_path: Path) -> None:
    # In a non-git directory git fails gracefully.
    result = git_diff_files(tmp_path)
    assert isinstance(result, list)


def test_run_tests_command_not_found(tmp_path: Path) -> None:
    result = run_tests(tmp_path, test_command=["definitely-not-a-real-command-xyz"])
    assert not result.passed
    assert "not found" in result.summary.lower()


def test_run_tests_ruff_clean(repo_root: Path | None = None) -> None:
    # Use the actual repo root.
    root = repo_root or Path(__file__).resolve().parents[2]
    result = run_tests(
        root,
        test_command=["ruff", "check", "conductor", "tests/conductor_tests"],
    )
    assert result.passed
    assert "All checks passed" in result.summary


def test_test_result_to_markdown() -> None:
    result = ValidationResult(
        passed=False,
        command="ruff check",
        returncode=1,
        stdout="",
        stderr="error",
        summary="bad",
    )
    assert "FAIL" in result.to_markdown()
    assert "ruff check" in result.to_markdown()
