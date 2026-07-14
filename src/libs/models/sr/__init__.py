"""SR model foundation package (V1.0).

Public entry point for immutable domain contracts and strict typed
configuration resolution.
"""

from __future__ import annotations

from .config import (
    AssociationConfig,
    DetectionConfig,
    LifecycleConfig,
    ResolvedSRConfig,
    RuntimeConfig,
    SRConfig,
    SRConfigResolver,
)
from .domain import (
    CandidateLevel,
    ClosedBar,
    ContractValidationError,
    SREvent,
    SREventType,
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
    create_initial_state,
    deterministic_hash,
    hash_candidate_level,
    hash_event,
    hash_snapshot,
    hash_zone_definition,
    require_utc,
)
from .lifecycle import SREngine

__all__ = [
    "AssociationConfig",
    "CandidateLevel",
    "ClosedBar",
    "ContractValidationError",
    "DetectionConfig",
    "LifecycleConfig",
    "ResolvedSRConfig",
    "RuntimeConfig",
    "SREngine",
    "SRConfig",
    "SRConfigResolver",
    "SREvent",
    "SREventType",
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
    "create_initial_state",
    "deterministic_hash",
    "hash_candidate_level",
    "hash_event",
    "hash_snapshot",
    "hash_zone_definition",
    "require_utc",
]
