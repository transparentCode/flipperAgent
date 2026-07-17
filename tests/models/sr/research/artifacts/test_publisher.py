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


@pytest.mark.parametrize(
    "member_name",
    (
        "../escaped.json",
        "/absolute.json",
        r"C:\\absolute.json",
        "subdir/member.json",
        "..\\escaped.json",
        "",
        ".",
        "..",
        "nul\x00member.json",
        1,
    ),
)
def test_publish_immutable_directory_rejects_unsafe_member_names_before_writes(
    tmp_path, member_name
):
    path = tmp_path / "bundle"

    with pytest.raises(ContractValidationError, match="member name is invalid"):
        publish_immutable_directory(
            path,
            {member_name: b"audit\n"},
            description="research artifact",
        )

    assert not path.exists()


def test_publish_immutable_directory_rejects_traversal_without_writing_outside_bundle(tmp_path):
    path = tmp_path / "bundle"
    escaped = tmp_path / "escaped.json"

    with pytest.raises(ContractValidationError, match="member name is invalid"):
        publish_immutable_directory(
            path,
            {"../escaped.json": b"escaped\n"},
            description="research artifact",
        )

    assert not path.exists()
    assert not escaped.exists()


@pytest.mark.parametrize("files", ({}, [("audit.json", b"audit\n")]))
def test_publish_immutable_directory_requires_non_empty_member_mapping(tmp_path, files):
    path = tmp_path / "bundle"

    with pytest.raises(ContractValidationError, match="members must be a non-empty mapping"):
        publish_immutable_directory(path, files, description="research artifact")

    assert not path.exists()


@pytest.mark.parametrize("payload", ("audit", bytearray(b"audit"), memoryview(b"audit")))
def test_publish_immutable_directory_requires_exact_byte_payloads(tmp_path, payload):
    path = tmp_path / "bundle"

    with pytest.raises(ContractValidationError, match="member payload must be bytes"):
        publish_immutable_directory(
            path,
            {"audit.json": payload},
            description="research artifact",
        )

    assert not path.exists()
