"""State-only checkpoint contracts for the SR v2 live facade.

The persistence boundary stores one canonical committed :class:`SRState` per
lane.  It deliberately does not know about structural results, events, or
history.  The live facade builds a fully serialized ``CheckpointRecord`` before
calling a repository, so a repository transaction only performs the compare
and set operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
from typing import Final, Protocol

from ..contracts import SR_V2_SCHEMA_VERSION, require_utc
from ..domain.state import SRState
from ..serialization.state_codec import encode_state

# The row binds its payload to the semantic SRState codec schema.  SQL table
# migrations own the physical table shape; there is no second checkpoint
# serialization format version here.
STATE_SCHEMA_VERSION: Final[int] = SR_V2_SCHEMA_VERSION


class CheckpointCorruptionError(ValueError):
    """Raised when persisted checkpoint evidence is not trustworthy."""


class CheckpointDisposition(str, Enum):
    """The result of one generation compare-and-set operation."""

    INSERTED = "INSERTED"
    UPDATED = "UPDATED"
    IDENTICAL = "IDENTICAL"
    CONFLICT = "CONFLICT"
    REJECTED_OLDER = "REJECTED_OLDER"


@dataclass(frozen=True, slots=True, kw_only=True)
class SRV2LaneIdentity:
    """Immutable venue/instrument/asset/config checkpoint key."""

    venue: str
    instrument_id: str
    asset: str
    config_fingerprint: str

    def __post_init__(self) -> None:
        for name in ("venue", "instrument_id", "asset", "config_fingerprint"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")


def state_payload_checksum(payload: bytes) -> str:
    """Return the canonical SHA-256 checksum for one encoded state payload."""

    if not isinstance(payload, bytes):
        raise TypeError("state payload must be bytes")
    return sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckpointRecord:
    """One validated, latest-only committed SR v2 state row."""

    identity: SRV2LaneIdentity
    schema_version: int
    generation: int
    cutoff: datetime
    state: SRState
    state_payload: bytes
    state_checksum: str

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SRV2LaneIdentity):
            raise TypeError("identity must be SRV2LaneIdentity")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != STATE_SCHEMA_VERSION
        ):
            raise CheckpointCorruptionError("unsupported checkpoint schema version")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation <= 0:
            raise CheckpointCorruptionError("checkpoint generation must be positive")
        cutoff = require_utc(self.cutoff, field_name="checkpoint cutoff")
        if not isinstance(self.state, SRState):
            raise TypeError("state must be SRState")
        if self.state.schema_version != self.schema_version:
            raise CheckpointCorruptionError("checkpoint state schema does not match row schema")
        if self.state.generation != self.generation:
            raise CheckpointCorruptionError("checkpoint generation does not match state")
        if self.state.last_trigger_at != cutoff:
            raise CheckpointCorruptionError("checkpoint cutoff does not match state")
        if (
            self.state.config_fingerprint != self.identity.config_fingerprint
            or self.state.venue != self.identity.venue
            or self.state.instrument_id != self.identity.instrument_id
            or self.state.asset != self.identity.asset
        ):
            raise CheckpointCorruptionError("checkpoint state identity does not match lane")
        if not isinstance(self.state_payload, bytes):
            raise TypeError("state_payload must be bytes")
        try:
            expected_payload = encode_state(self.state)
        except (TypeError, ValueError) as exc:
            raise CheckpointCorruptionError("checkpoint state cannot be encoded") from exc
        if self.state_payload != expected_payload:
            raise CheckpointCorruptionError("checkpoint payload is not canonical state")
        if not isinstance(self.state_checksum, str) or self.state_checksum != state_payload_checksum(self.state_payload):
            raise CheckpointCorruptionError("checkpoint checksum does not match payload")
        object.__setattr__(self, "cutoff", cutoff)

    @classmethod
    def from_state(cls, *, identity: SRV2LaneIdentity, state: SRState) -> CheckpointRecord:
        """Serialize one committed state before any repository transaction."""

        if not isinstance(state, SRState):
            raise TypeError("state must be SRState")
        if state.last_trigger_at is None:
            raise ValueError("genesis state cannot be persisted as a checkpoint")
        payload = encode_state(state)
        return cls(
            identity=identity,
            schema_version=state.schema_version,
            generation=state.generation,
            cutoff=state.last_trigger_at,
            state=state,
            state_payload=payload,
            state_checksum=state_payload_checksum(payload),
        )


def _validate_expected_generation(expected_generation: int | None) -> None:
    if expected_generation is not None and (
        isinstance(expected_generation, bool)
        or not isinstance(expected_generation, int)
        or expected_generation < 0
    ):
        raise ValueError("expected_generation must be non-negative or None")


def classify_commit(
    current: CheckpointRecord | None,
    proposal: CheckpointRecord,
    *,
    expected_generation: int | None,
) -> CheckpointDisposition:
    """Classify one generation-CAS proposal with a deterministic total order.

    Positions are ordered first by generation and then by cutoff.  An exact
    same-position, same-payload retry is idempotent even when its expected
    generation became stale.  A position with both coordinates no newer than
    the current row is stale.  A newer position is only an update when it is
    exactly the next generation, advances the cutoff, and the caller's
    expected generation still matches.  All other combinations are conflicts,
    including a generation/cutoff pair that moves in opposite directions.
    """

    _validate_expected_generation(expected_generation)
    if not isinstance(proposal, CheckpointRecord):
        raise TypeError("proposal must be CheckpointRecord")
    if current is not None and not isinstance(current, CheckpointRecord):
        raise TypeError("current must be CheckpointRecord or None")
    if current is not None and current.identity != proposal.identity:
        raise CheckpointCorruptionError("checkpoint identities do not match")
    if current is None:
        return (
            CheckpointDisposition.INSERTED
            if expected_generation is None and proposal.generation == 1
            else CheckpointDisposition.CONFLICT
        )

    same_position = current.generation == proposal.generation and current.cutoff == proposal.cutoff
    if same_position:
        if proposal.state_payload == current.state_payload:
            return CheckpointDisposition.IDENTICAL
        return CheckpointDisposition.CONFLICT

    if (
        proposal.generation <= current.generation
        and proposal.cutoff <= current.cutoff
    ):
        return CheckpointDisposition.REJECTED_OLDER
    if proposal.generation <= current.generation or proposal.cutoff <= current.cutoff:
        return CheckpointDisposition.CONFLICT
    if expected_generation != current.generation:
        return CheckpointDisposition.CONFLICT
    if (
        proposal.generation == current.generation + 1
        and proposal.cutoff > current.cutoff
    ):
        return CheckpointDisposition.UPDATED
    return CheckpointDisposition.CONFLICT


class CheckpointRepository(Protocol):
    """Async latest-state repository supplied to ``LiveRuntime``."""

    async def load(self, identity: SRV2LaneIdentity) -> CheckpointRecord | None:
        """Load the validated latest checkpoint for one lane."""

    async def commit(
        self,
        proposal: CheckpointRecord,
        *,
        expected_generation: int | None,
    ) -> CheckpointDisposition:
        """Compare and set a serialized proposal."""


__all__ = [
    "STATE_SCHEMA_VERSION",
    "CheckpointCorruptionError",
    "CheckpointDisposition",
    "CheckpointRecord",
    "CheckpointRepository",
    "SRV2LaneIdentity",
    "classify_commit",
    "state_payload_checksum",
]
