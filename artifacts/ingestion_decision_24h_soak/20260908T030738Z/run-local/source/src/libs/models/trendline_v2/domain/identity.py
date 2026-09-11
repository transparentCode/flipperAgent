"""Deterministic content-addressed identity for domain values."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .validation import ContractValidationError, primitive, require_string


def canonical_json(value: Any) -> str:
    return json.dumps(
        primitive(value),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def deterministic_hash(namespace: str, value: Any) -> str:
    namespace = require_string(namespace, field_name="identity namespace")
    payload = f"{namespace}:".encode("utf-8") + canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def require_hash(value: Any, *, field_name: str) -> str:
    value = require_string(value, field_name=field_name)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContractValidationError(f"{field_name} must be lowercase SHA-256 hex")
    return value


def provider_identity(provider_name: str, provider_version: str) -> str:
    return deterministic_hash(
        "trendline_v2_provider",
        {
            "name": require_string(provider_name, field_name="provider_name"),
            "version": require_string(provider_version, field_name="provider_version"),
        },
    )


__all__ = [
    "canonical_json",
    "deterministic_hash",
    "provider_identity",
    "require_hash",
]
