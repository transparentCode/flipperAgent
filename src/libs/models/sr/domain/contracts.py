"""Compatibility facade for immutable SR domain contracts."""

from __future__ import annotations

from .bars import ClosedBar, SRStateKey
from .candidates import CandidateLevel
from .errors import ContractValidationError
from .events import SREvent, SREventType
from .geometry import ZoneGeometry
from .identity import canonical_json, deterministic_hash
from .snapshots import SRSnapshot
from .state import SR_SCHEMA_VERSION, SRState
from .zones import (
    ZoneDefinition,
    ZoneRecord,
    ZoneRuntimeState,
    ZoneSide,
    ZoneStatus,
)

__all__ = [
    "ContractValidationError",
    "ZoneSide",
    "ZoneStatus",
    "SR_SCHEMA_VERSION",
    "SREventType",
    "SRStateKey",
    "ClosedBar",
    "ZoneGeometry",
    "CandidateLevel",
    "ZoneDefinition",
    "ZoneRuntimeState",
    "ZoneRecord",
    "SREvent",
    "SRState",
    "SRSnapshot",
    "canonical_json",
    "deterministic_hash",
]
