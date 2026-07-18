"""SR domain language: immutable contracts, identities, and validation."""

from __future__ import annotations

from .bars import ClosedBar, SRStateKey
from .candidates import CandidateLevel
from .errors import ContractValidationError
from .events import SREvent, SREventType
from .geometry import ZoneGeometry
from .identity import canonical_json, deterministic_hash
from .snapshots import SRSnapshot
from .state import SR_SCHEMA_VERSION, SRState
from .zones import ZoneDefinition, ZoneRecord, ZoneRuntimeState, ZoneSide, ZoneStatus
from .identity import (
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
