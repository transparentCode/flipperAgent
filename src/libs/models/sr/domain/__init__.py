"""SR domain language: immutable contracts, identities, and validation."""

from __future__ import annotations

from .contracts import (
    CandidateLevel,
    ClosedBar,
    SREvent,
    SREventType,
    SR_SCHEMA_VERSION,
    SRState,
    SRStateKey,
    SRSnapshot,
    ZoneDefinition,
    ZoneGeometry,
    ZoneRecord,
    ZoneRuntimeState,
    ZoneSide,
    ZoneStatus,
    canonical_json,
    deterministic_hash,
)
from .identity import (
    ContractValidationError,
    hash_candidate_level,
    hash_event,
    hash_snapshot,
    hash_zone_definition,
    require_utc,
)
from .factory import create_initial_state

__all__ = [
    "CandidateLevel",
    "ClosedBar",
    "ContractValidationError",
    "create_initial_state",
    "SREvent",
    "SREventType",
    "SR_SCHEMA_VERSION",
    "SRState",
    "SRStateKey",
    "SRSnapshot",
    "ZoneDefinition",
    "ZoneGeometry",
    "ZoneRecord",
    "ZoneRuntimeState",
    "ZoneSide",
    "ZoneStatus",
    "canonical_json",
    "deterministic_hash",
    "hash_candidate_level",
    "hash_event",
    "hash_snapshot",
    "hash_zone_definition",
    "require_utc",
]
