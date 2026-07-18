from __future__ import annotations

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.research.artifacts.manifest import (
    member_metadata,
    validate_member_metadata,
)


def test_member_metadata_binds_name_digest_and_exact_byte_length():
    data = b"audit\n"

    assert member_metadata("audit.json", data) == {
        "name": "audit.json",
        "sha256": "8818d016bf6ad2955510ea05054b6287e0b6732ac22a6c323fcda06476d04a72",
        "byte_length": 6,
    }


@pytest.mark.parametrize(
    ("name", "payload"),
    (
        ("../escaped.json", b"audit\n"),
        ("audit.json", "audit"),
    ),
)
def test_member_metadata_requires_safe_name_and_exact_bytes(name, payload):
    with pytest.raises(ContractValidationError):
        member_metadata(name, payload)


@pytest.mark.parametrize(
    "metadata",
    (
        {},
        {"name": "wrong.json", "sha256": "a" * 64, "byte_length": 0},
        {"name": "audit.json", "sha256": "a" * 63, "byte_length": 0},
        {"name": "audit.json", "sha256": "g" * 64, "byte_length": 0},
        {"name": "audit.json", "sha256": "A" * 64, "byte_length": 0},
        {"name": "audit.json", "sha256": "a" * 64, "byte_length": -1},
    ),
)
def test_member_metadata_validation_rejects_malformed_values(metadata):
    with pytest.raises(ContractValidationError, match="audit member metadata is malformed"):
        validate_member_metadata(
            metadata,
            expected_name="audit.json",
            description="audit member",
        )
