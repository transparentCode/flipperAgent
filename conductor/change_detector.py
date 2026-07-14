"""Detect code changes and test status for conductor checkpoint gates."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ValidationResult:
    """Summary of a test/lint run."""

    passed: bool
    command: str
    returncode: int
    stdout: str
    stderr: str
    summary: str

    def to_markdown(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"**{status}** — `{self.command}` (exit {self.returncode})\n{self.summary}"


def git_diff_files(repo_root: Path, base_ref: str = "HEAD") -> list[str]:
    """Return list of files changed since base_ref."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", base_ref],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return []
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    except FileNotFoundError:
        return []


def git_worktree_is_clean(repo_root: Path) -> bool:
    """Return True if the git worktree has no uncommitted changes."""
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode == 0 and not proc.stdout.strip()
    except FileNotFoundError:
        return True


def run_tests(
    repo_root: Path,
    target_paths: list[str] | None = None,
    test_command: list[str] | None = None,
) -> ValidationResult:
    """Run the project test suite or a subset and return a summary."""
    cmd = test_command or [
        "ruff",
        "check",
        "conductor",
        "tests/conductor_tests",
    ]
    if target_paths:
        cmd = cmd + target_paths
    try:
        proc = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
        output = (proc.stdout + "\n" + proc.stderr).strip()
        passed = proc.returncode == 0
        summary = output.splitlines()[-1] if output else "No output"
        return ValidationResult(
            passed=passed,
            command=" ".join(cmd),
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            summary=summary,
        )
    except FileNotFoundError as exc:
        return ValidationResult(
            passed=False,
            command=" ".join(cmd),
            returncode=-1,
            stdout="",
            stderr=str(exc),
            summary=f"Test command not found: {exc}",
        )
    except subprocess.TimeoutExpired:
        return ValidationResult(
            passed=False,
            command=" ".join(cmd),
            returncode=-1,
            stdout="",
            stderr="",
            summary="Test run exceeded 300s timeout",
        )


def summarize_changes_and_tests(
    repo_root: Path,
    base_ref: str = "HEAD",
    test_command: list[str] | None = None,
    target_paths: list[str] | None = None,
) -> tuple[list[str], ValidationResult]:
    """Convenience helper returning (changed_files, test_result)."""
    changed = git_diff_files(repo_root, base_ref)
    test_result = run_tests(repo_root, target_paths=target_paths, test_command=test_command)
    return changed, test_result
