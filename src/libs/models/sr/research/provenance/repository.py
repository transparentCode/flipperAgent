"""Fail-closed repository identity and path-resolution primitives."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath
import re
import subprocess

from libs.models.sr.domain.contracts import ContractValidationError


_COMMIT_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def resolve_repository_root(repo_root: str | Path) -> Path:
    """Resolve an existing repository root directory deterministically."""

    try:
        root = Path(repo_root).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ContractValidationError("repository root must be an existing directory") from exc
    if not root.is_dir():
        raise ContractValidationError("repository root must be an existing directory")
    return root


def repository_commit(repo_root: str | Path) -> str:
    """Return exact lowercase Git HEAD SHA for an existing repository root."""

    root = resolve_repository_root(repo_root)
    try:
        output = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContractValidationError("cannot determine repository commit") from exc
    commit = output.rstrip("\n")
    if output != f"{commit}\n" or _COMMIT_SHA.fullmatch(commit) is None:
        raise ContractValidationError("cannot determine repository commit")
    return commit


def _path_error(field_name: str) -> ContractValidationError:
    return ContractValidationError(f"{field_name} escaped repository root")


def resolve_repository_path(
    repo_root: str | Path,
    relative_path: str,
    *,
    field_name: str,
) -> Path:
    """Resolve a safe repository-relative path without allowing root escape."""

    root = resolve_repository_root(repo_root)
    if type(relative_path) is not str:
        raise _path_error(field_name)
    relative = Path(relative_path)
    windows_relative = PureWindowsPath(relative_path)
    if (
        "\x00" in relative_path
        or relative.is_absolute()
        or windows_relative.is_absolute()
        or windows_relative.drive
        or ".." in relative.parts
        or ".." in windows_relative.parts
    ):
        raise _path_error(field_name)
    try:
        resolved = (root / relative).resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _path_error(field_name) from exc
    if resolved != root and root not in resolved.parents:
        raise _path_error(field_name)
    return resolved


__all__ = [
    "repository_commit",
    "resolve_repository_path",
    "resolve_repository_root",
]
