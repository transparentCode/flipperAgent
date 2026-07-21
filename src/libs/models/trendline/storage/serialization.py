"""Snapshot serialization owned independently from repository protocols."""

from __future__ import annotations

import json

from ..domain.identity import canonical_json
from ..domain.snapshots import TrendlineFamilySnapshot
from ..domain.validation import ContractValidationError


def serialize_snapshot(snapshot: TrendlineFamilySnapshot) -> str:
    return canonical_json(snapshot.to_dict())


def deserialize_snapshot(payload: str) -> TrendlineFamilySnapshot:
    if not isinstance(payload, str):
        raise ContractValidationError("snapshot payload must be a JSON string")
    try:
        return TrendlineFamilySnapshot.from_dict(json.loads(payload))
    except ContractValidationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ContractValidationError("snapshot payload is not valid JSON") from exc


__all__ = ["deserialize_snapshot", "serialize_snapshot"]
