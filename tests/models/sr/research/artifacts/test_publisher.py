from __future__ import annotations

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.research.artifacts.publisher import publish_immutable_directory


def test_publish_immutable_directory_is_atomic_and_idempotent_for_exact_bytes(tmp_path):
    path = tmp_path / "bundle"
    files = {"manifest.json": b"manifest\n", "audit.json": b"audit\n"}

    publish_immutable_directory(path, files, description="research artifact")
    publish_immutable_directory(path, files, description="research artifact")

    assert {member.name for member in path.iterdir()} == set(files)
    assert {name: (path / name).read_bytes() for name in files} == files


def test_publish_immutable_directory_rejects_different_existing_bytes(tmp_path):
    path = tmp_path / "bundle"
    publish_immutable_directory(path, {"audit.json": b"first\n"}, description="research artifact")

    with pytest.raises(ContractValidationError, match="existing research artifact bytes differ"):
        publish_immutable_directory(path, {"audit.json": b"second\n"}, description="research artifact")


def test_publish_immutable_directory_rejects_unexpected_existing_members(tmp_path):
    path = tmp_path / "bundle"
    publish_immutable_directory(path, {"audit.json": b"audit\n"}, description="research artifact")
    (path / "extra.json").write_bytes(b"extra\n")

    with pytest.raises(ContractValidationError, match="unexpected members"):
        publish_immutable_directory(path, {"audit.json": b"audit\n"}, description="research artifact")
