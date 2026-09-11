"""Bounded, replay-safe structural state.

State is intentionally only the mutable structural snapshot. Transition and
feature evidence are outputs of one step and belong to the caller/research
trace; persisting either in the state creates two competing event authorities.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from ..contracts import SR_V2_SCHEMA_VERSION, FrozenMapping, require_utc
from .identity import fingerprint_sequence_hash
from .zones import ZoneRecord


@dataclass(frozen=True, slots=True, kw_only=True)
class SRState:
    schema_version: int = SR_V2_SCHEMA_VERSION
    config_fingerprint: str
    generation: int
    venue: str
    instrument_id: str
    asset: str
    last_trigger_at: datetime | None = None
    source_cutoffs: Mapping[str, datetime] = field(default_factory=dict)
    source_fingerprints: Mapping[str, str] = field(default_factory=dict)
    source_fingerprint_sequences: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    active_lineages: tuple[ZoneRecord, ...] = ()
    terminal_tombstones: tuple[ZoneRecord, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int):
            raise TypeError("schema_version must be an integer")
        if self.schema_version != SR_V2_SCHEMA_VERSION:
            raise ValueError("unsupported SR v2 state schema version")
        if not isinstance(self.config_fingerprint, str) or not self.config_fingerprint.strip():
            raise ValueError("config_fingerprint must be non-empty")
        for name in ("venue", "instrument_id", "asset"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation < 0:
            raise ValueError("generation must be a non-negative integer")
        if self.last_trigger_at is not None:
            require_utc(self.last_trigger_at, field_name="last_trigger_at")
        cutoffs = dict(self.source_cutoffs)
        for key, value in cutoffs.items():
            if not isinstance(key, str) or not key.strip():
                raise TypeError("source_cutoffs keys must be non-empty strings")
            require_utc(value, field_name=f"source_cutoffs[{key}]")
        fingerprints = dict(self.source_fingerprints)
        for key, value in fingerprints.items():
            if not isinstance(key, str) or not key.strip():
                raise TypeError("source_fingerprints keys must be non-empty strings")
            if not isinstance(value, str) or not value.strip():
                raise TypeError("source_fingerprints values must be non-empty strings")
        if set(cutoffs) != set(fingerprints):
            raise ValueError("source cutoffs and fingerprints must cover the same timeframes")
        sequences = {key: tuple(value) for key, value in self.source_fingerprint_sequences.items()}
        for key, values in sequences.items():
            if not isinstance(key, str) or not key.strip():
                raise TypeError("source_fingerprint_sequences keys must be non-empty strings")
            if not values or any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError("source_fingerprint_sequences values must be non-empty strings")
            if key not in fingerprints:
                raise ValueError("source fingerprint sequence has no aggregate fingerprint")
            if fingerprint_sequence_hash(values) != fingerprints[key]:
                raise ValueError("source fingerprint aggregate does not match its sequence")
        if set(fingerprints) != set(sequences):
            raise ValueError("source fingerprints and sequences must cover the same timeframes")
        if self.last_trigger_at is None:
            if self.generation != 0:
                raise ValueError("genesis state must have generation zero")
            if cutoffs or fingerprints or sequences:
                raise ValueError("genesis state must not contain source identities")
            if self.active_lineages or self.terminal_tombstones:
                raise ValueError("genesis state must not contain lineages")
        else:
            if self.generation <= 0:
                raise ValueError("committed state must have positive generation")
            if not cutoffs or not fingerprints or not sequences:
                raise ValueError("committed state must contain source identities")
        active = tuple(self.active_lineages)
        terminal = tuple(self.terminal_tombstones)
        if any(not isinstance(item, ZoneRecord) for item in active + terminal):
            raise TypeError("state lineages must contain ZoneRecord values")
        ids = [item.lineage.zone_id for item in active + terminal]
        if len(ids) != len(set(ids)):
            raise ValueError("state lineages must have unique IDs")
        object.__setattr__(self, "source_cutoffs", FrozenMapping(dict(sorted(cutoffs.items()))))
        object.__setattr__(self, "source_fingerprints", FrozenMapping(dict(sorted(fingerprints.items()))))
        object.__setattr__(
            self,
            "source_fingerprint_sequences",
            FrozenMapping({key: tuple(sequences[key]) for key in sorted(sequences)}),
        )
        object.__setattr__(self, "active_lineages", tuple(sorted(active, key=lambda item: item.lineage.zone_id)))
        object.__setattr__(self, "terminal_tombstones", tuple(sorted(terminal, key=lambda item: item.lineage.zone_id)))


def create_initial_state(
    *,
    config_fingerprint: str,
    venue: str,
    instrument_id: str,
    asset: str,
) -> SRState:
    """Create the only valid empty structural state."""

    return SRState(
        config_fingerprint=config_fingerprint,
        generation=0,
        venue=venue,
        instrument_id=instrument_id,
        asset=asset,
    )


__all__ = ["SRState", "ZoneRecord", "create_initial_state"]
