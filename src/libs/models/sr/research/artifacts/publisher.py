"""Atomic, immutable directory publication for research artifacts."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Mapping

from libs.models.sr.domain.contracts import ContractValidationError

from .path_safety import reject_symlink_components, require_regular_file


def publish_immutable_directory(
    path: str | Path,
    files: Mapping[str, bytes],
    *,
    description: str,
) -> None:
    """Atomically publish exact bytes, accepting only an identical prior bundle."""

    target = Path(path)
    reject_symlink_components(target, description=description)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if (
            not target.is_dir()
            or target.is_symlink()
            or {item.name for item in target.iterdir()} != set(files)
        ):
            raise ContractValidationError(
                f"existing {description} path has unexpected members"
            )
        for name, data in files.items():
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
        for name, data in files.items():
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
