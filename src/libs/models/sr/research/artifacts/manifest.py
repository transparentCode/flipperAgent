"""Generic artifact-member metadata primitives.

This module deliberately validates only member metadata.  Individual studies
remain responsible for their own semantic manifest schema and identities.
"""

from __future__ import annotations

from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError

from .canonical_json import sha256_hex


def member_metadata(name: str, data: bytes) -> dict[str, Any]:
    """Build canonical metadata for one published artifact member."""

    return {"name": name, "sha256": sha256_hex(data), "byte_length": len(data)}


def validate_member_metadata(
    value: Any,
    *,
    expected_name: str,
    description: str,
) -> dict[str, Any]:
    """Require exact, internally well-formed metadata for one named member."""

    if (
        type(value) is not dict
        or set(value) != {"name", "sha256", "byte_length"}
        or value.get("name") != expected_name
        or type(value.get("sha256")) is not str
        or len(value["sha256"]) != 64
        or type(value.get("byte_length")) is not int
        or value["byte_length"] < 0
    ):
        raise ContractValidationError(f"{description} metadata is malformed")
    return value


__all__ = ["member_metadata", "validate_member_metadata"]
