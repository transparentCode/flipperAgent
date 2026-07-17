"""Generic artifact-member metadata primitives.

This module deliberately validates only member metadata.  Individual studies
remain responsible for their own semantic manifest schema and identities.
"""

from __future__ import annotations

import re
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError

from .canonical_json import sha256_hex


_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def validate_member_name(name: Any, *, description: str) -> str:
    """Require one safe, non-empty artifact-member basename."""

    if (
        type(name) is not str
        or not name
        or name in {".", ".."}
        or "\x00" in name
        or "/" in name
        or "\\" in name
    ):
        raise ContractValidationError(f"{description} name is invalid")
    return name


def validate_member_bytes(data: Any, *, description: str) -> bytes:
    """Require exact byte payloads for immutable artifact members."""

    if type(data) is not bytes:
        raise ContractValidationError(f"{description} payload must be bytes")
    return data


def member_metadata(name: str, data: bytes) -> dict[str, Any]:
    """Build canonical metadata for one published artifact member."""

    validated_name = validate_member_name(name, description="artifact member")
    validated_data = validate_member_bytes(data, description="artifact member")
    return {
        "name": validated_name,
        "sha256": sha256_hex(validated_data),
        "byte_length": len(validated_data),
    }


def validate_member_metadata(
    value: Any,
    *,
    expected_name: str,
    description: str,
) -> dict[str, Any]:
    """Require exact, internally well-formed metadata for one named member."""

    validated_name = validate_member_name(
        expected_name,
        description=f"{description} expected member",
    )
    if (
        type(value) is not dict
        or set(value) != {"name", "sha256", "byte_length"}
        or value.get("name") != validated_name
        or type(value.get("sha256")) is not str
        or _SHA256_HEX.fullmatch(value["sha256"]) is None
        or type(value.get("byte_length")) is not int
        or value["byte_length"] < 0
    ):
        raise ContractValidationError(f"{description} metadata is malformed")
    return value


__all__ = [
    "member_metadata",
    "validate_member_bytes",
    "validate_member_metadata",
    "validate_member_name",
]
