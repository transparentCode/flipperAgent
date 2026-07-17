"""Public SR observation and evaluation contracts."""

from __future__ import annotations

from .contracts import (
    ObservedEvent,
    SREvaluationTrace,
    SR_EVALUATION_SCHEMA_VERSION,
    SnapshotReference,
    ZoneObservation,
    ZoneRenderKind,
)
from .diagnostics import (
    SRDiagnostics,
    SnapshotDiagnostics,
    ZoneDiagnostics,
    compute_diagnostics,
)
from .trace_builder import build_evaluation_trace

__all__ = [
    "ObservedEvent",
    "SRDiagnostics",
    "SREvaluationTrace",
    "SR_EVALUATION_SCHEMA_VERSION",
    "SnapshotDiagnostics",
    "SnapshotReference",
    "ZoneDiagnostics",
    "ZoneObservation",
    "ZoneRenderKind",
    "build_evaluation_trace",
    "compute_diagnostics",
]
