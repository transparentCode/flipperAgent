"""Shared immutable artifact primitives for SR research studies."""

from __future__ import annotations

from .canonical_json import canonical_json_bytes, sha256_hex
from .manifest import member_metadata, validate_member_metadata
from .path_safety import reject_symlink_components, require_regular_file
from .publisher import publish_immutable_directory
from .validator import load_strict_json


__all__ = [
    "canonical_json_bytes",
    "load_strict_json",
    "member_metadata",
    "publish_immutable_directory",
    "reject_symlink_components",
    "require_regular_file",
    "sha256_hex",
    "validate_member_metadata",
]
