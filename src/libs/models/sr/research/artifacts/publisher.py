"""Atomic, immutable directory publication for research artifacts."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from libs.models.sr.domain import ContractValidationError

from .manifest import validate_member_bytes, validate_member_name
from .path_safety import reject_symlink_components, require_regular_file


def _validate_files(files: Any, *, description: str) -> Mapping[str, bytes]:
    if not isinstance(files, Mapping) or not files:
        raise ContractValidationError(f"{description} members must be a non-empty mapping")
    for name, data in files.items():
        validate_member_name(name, description=f"{description} member")
        validate_member_bytes(data, description=f"{description} member")
    return files


def publish_immutable_directory(
    path: str | Path,
    files: Mapping[str, bytes],
    *,
    description: str,
) -> None:
    """Atomically publish exact bytes, accepting only an identical prior bundle."""

    validated_files = _validate_files(files, description=description)
    target = Path(path)
    reject_symlink_components(target, description=description)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if (
            not target.is_dir()
            or target.is_symlink()
            or {item.name for item in target.iterdir()} != set(validated_files)
        ):
            raise ContractValidationError(
                f"existing {description} path has unexpected members"
            )
        for name, data in validated_files.items():
            member_path = target / name
            require_regular_file(member_path, description=f"{description} member")
            try:
                current = member_path.read_bytes()
            except OSError as exc:
                raise ContractValidationError(
                    f"existing {description} member cannot be read"
                ) from exc
            if current != data:
                raise ContractValidationError(f"existing {description} bytes differ")
        return

    temporary = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent)
    )
    try:
        for name, data in validated_files.items():
            (temporary / name).write_bytes(data)
        os.replace(temporary, target)
    except OSError as exc:
        raise ContractValidationError(
            f"atomic {description} publication failed"
        ) from exc
    finally:
        if temporary.exists():
            for item in temporary.iterdir():
                item.unlink()
            temporary.rmdir()


__all__ = ["publish_immutable_directory"]
