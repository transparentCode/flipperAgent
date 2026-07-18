"""SR model foundation package (V1.0).

Public entry point for immutable domain contracts and strict typed
configuration resolution.
"""

from __future__ import annotations

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

_CONFIG_EXPORTS = {
    "AssociationConfig",
    "DetectionConfig",
    "LifecycleConfig",
    "ResolvedSRConfig",
    "RuntimeConfig",
    "SRConfig",
    "SRConfigResolver",
}


def __getattr__(name: str) -> object:
    """Load non-domain public exports without coupling domain import to config."""
    if name in _CONFIG_EXPORTS:
        from .config import (
            AssociationConfig,
            DetectionConfig,
            LifecycleConfig,
            ResolvedSRConfig,
            RuntimeConfig,
            SRConfig,
            SRConfigResolver,
        )

        exports = {
            "AssociationConfig": AssociationConfig,
            "DetectionConfig": DetectionConfig,
            "LifecycleConfig": LifecycleConfig,
            "ResolvedSRConfig": ResolvedSRConfig,
            "RuntimeConfig": RuntimeConfig,
            "SRConfig": SRConfig,
            "SRConfigResolver": SRConfigResolver,
        }
        globals().update(exports)
        return exports[name]
    if name == "SREngine":
        from .lifecycle import SREngine

        globals()[name] = SREngine
        return SREngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

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
