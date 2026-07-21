"""Primitive domain serialization without storage ownership."""

from __future__ import annotations

from typing import Any

from .identity import canonical_json
from .validation import _primitive


def to_primitive(value: Any) -> Any:
    """Return the canonical immutable-domain primitive representation."""

    return _primitive(value)


def serialize_domain(value: Any) -> str:
    """Serialize a domain value with canonical identity-safe JSON rules."""

    return canonical_json(value)


__all__ = ["serialize_domain", "to_primitive"]
