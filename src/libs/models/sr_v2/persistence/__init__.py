"""SR v2 state-only checkpoint contracts and injected-pool adapter."""

from .contracts import (
    STATE_SCHEMA_VERSION,
    CheckpointCorruptionError,
    CheckpointDisposition,
    CheckpointRecord,
    CheckpointRepository,
    SRV2LaneIdentity,
    classify_commit,
    state_payload_checksum,
)
from .timescale import TimescaleCheckpointRepository, apply_schema

__all__ = [
    "STATE_SCHEMA_VERSION",
    "CheckpointCorruptionError",
    "CheckpointDisposition",
    "CheckpointRecord",
    "CheckpointRepository",
    "SRV2LaneIdentity",
    "TimescaleCheckpointRepository",
    "apply_schema",
    "classify_commit",
    "state_payload_checksum",
]
