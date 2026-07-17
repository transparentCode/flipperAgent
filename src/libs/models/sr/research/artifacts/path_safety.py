"""Fail-closed filesystem guards for immutable research artifacts."""

from __future__ import annotations

from pathlib import Path
import stat

from libs.models.sr.domain.identity import ContractValidationError


def require_regular_file(path: str | Path, *, description: str) -> None:
    """Require an existing non-symlink regular file without resolving it."""

    member_path = Path(path)
    try:
        mode = member_path.lstat().st_mode
    except OSError as exc:
        raise ContractValidationError(
            f"{description} cannot be read: {member_path}"
        ) from exc
    if not stat.S_ISREG(mode):
        raise ContractValidationError(
            f"{description} must be a regular file: {member_path}"
        )


def reject_symlink_components(path: str | Path, *, description: str) -> None:
    """Reject any existing symlink in a path before it is resolved or used."""

    candidate = Path(path)
    candidate = candidate if candidate.is_absolute() else Path.cwd() / candidate
    current = Path(candidate.anchor)
    for component in candidate.parts[1:]:
        if component == "..":
            current = current.parent
            continue
        current /= component
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            break
        except OSError as exc:
            raise ContractValidationError(
                f"{description} path cannot be inspected: {current}"
            ) from exc
        if stat.S_ISLNK(mode):
            raise ContractValidationError(
                f"{description} path contains symlink: {current}"
            )


__all__ = ["reject_symlink_components", "require_regular_file"]
