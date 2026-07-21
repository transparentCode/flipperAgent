"""Deterministic canonical JSON, hashes, and identifiers."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .validation import _primitive, _string

def canonical_json(value: Any) -> str:
    return json.dumps(_primitive(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def deterministic_id(kind: str, payload: Any) -> str:
    return str(uuid5(NAMESPACE_URL, f"trendline-family:{_string(kind, field_name='identity kind')}:{canonical_json(payload)}"))


def deterministic_hash(payload: Any) -> str:
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()
