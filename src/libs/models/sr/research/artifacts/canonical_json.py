"""Canonical JSON byte primitives for immutable research artifacts."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from libs.models.sr.domain.identity import canonical_json


def canonical_json_bytes(payload: Any) -> bytes:
    """Encode canonical JSON as UTF-8 with exactly one trailing newline."""

    return (canonical_json(payload) + "\n").encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Return the SHA-256 hexadecimal digest for exact artifact bytes."""

    return sha256(data).hexdigest()


__all__ = ["canonical_json_bytes", "sha256_hex"]
