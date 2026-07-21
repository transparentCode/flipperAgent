"""Canonical primitive serialization for domain contracts."""

from __future__ import annotations

from typing import Any

from .identity import canonical_json
from .validation import primitive


def to_primitive(value: Any) -> Any:
    return primitive(value)


def serialize_domain(value: Any) -> str:
    return canonical_json(value)


__all__ = ["serialize_domain", "to_primitive"]
