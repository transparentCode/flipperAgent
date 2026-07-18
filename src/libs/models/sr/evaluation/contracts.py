"""Compatibility facade for immutable SR evaluation contracts."""

from __future__ import annotations

from libs.models.sr.domain.errors import ContractValidationError  # noqa: F401
from libs.models.sr.domain.events import SREventType  # noqa: F401
from libs.models.sr.domain.zones import ZoneSide, ZoneStatus  # noqa: F401

from .observations import (
    ObservedEvent,
    SR_EVALUATION_SCHEMA_VERSION,
    SnapshotReference,
    ZoneObservation,
    ZoneRenderKind,
)
from .traces import SREvaluationTrace

__all__ = [
    "ObservedEvent",
    "SREvaluationTrace",
    "SR_EVALUATION_SCHEMA_VERSION",
    "SnapshotReference",
    "ZoneObservation",
    "ZoneRenderKind",
]
