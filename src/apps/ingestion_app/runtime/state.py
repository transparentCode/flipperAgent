"""Shared runtime state contracts.

The controller owns desired state. Supervisors report only the observed state
of their current generation through :class:`SupervisorSnapshot`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DesiredRuntimeState(StrEnum):
    """Runtime-wide desired state controlled by the runtime controller."""

    RUNNING = "running"
    PAUSED = "paused"


class RuntimeState(StrEnum):
    """Observed state of an in-memory runtime generation."""

    STOPPED = "stopped"
    STARTING = "starting"
    LIVE = "live"
    RECOVERING = "recovering"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class LaneFault:
    """One instrument held out of live ingestion while its history is repaired.

    ``reason`` is ``"no_closed_candle_in_window"`` or ``"recovery_exhausted"``.
    ``detail`` is the recovery error text, or empty for the probe case. Both
    timestamps are UTC.
    """

    venue: str
    instrument_id: str
    reason: str
    detail: str
    excluded_since: datetime
    next_retry_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    """Public controller-composed runtime status."""

    desired_state: DesiredRuntimeState
    state: RuntimeState
    last_error: str | None
    not_live_seconds: float | None = None
    excluded_lanes: tuple[LaneFault, ...] = ()


@dataclass(frozen=True, slots=True)
class SupervisorSnapshot:
    """Observed status reported by one runtime supervisor generation."""

    state: RuntimeState
    last_error: str | None
    not_live_seconds: float | None = None
    excluded_lanes: tuple[LaneFault, ...] = ()


__all__ = [
    "DesiredRuntimeState",
    "LaneFault",
    "RuntimeSnapshot",
    "RuntimeState",
    "SupervisorSnapshot",
]
