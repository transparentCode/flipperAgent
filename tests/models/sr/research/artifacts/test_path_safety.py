from __future__ import annotations

from pathlib import Path

import pytest

from libs.models.sr.domain.identity import ContractValidationError
from libs.models.sr.research.artifacts.path_safety import (
    reject_symlink_components,
    require_regular_file,
)


def test_regular_file_guard_accepts_a_real_file(tmp_path: Path) -> None:
    path = tmp_path / "member.json"
    path.write_text("{}", encoding="utf-8")

    require_regular_file(path, description="test member")


@pytest.mark.parametrize("kind", ("directory", "symlink"))
def test_regular_file_guard_rejects_non_regular_paths(
    tmp_path: Path, kind: str
) -> None:
    path = tmp_path / "member.json"
    if kind == "directory":
        path.mkdir()
    else:
        target = tmp_path / "target.json"
        target.write_text("{}", encoding="utf-8")
        path.symlink_to(target)

    with pytest.raises(ContractValidationError, match="regular file"):
        require_regular_file(path, description="test member")


def test_symlink_component_guard_rejects_a_linked_parent(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(ContractValidationError, match="contains symlink"):
        reject_symlink_components(
            linked_parent / "artifact" / "manifest.json",
            description="test artifact",
        )


def test_symlink_component_guard_permits_nonexistent_tail(tmp_path: Path) -> None:
    reject_symlink_components(
        tmp_path / "missing" / "artifact" / "manifest.json",
        description="test artifact",
    )
