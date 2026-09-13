"""Shared runtime state contracts.

The controller owns desired state. Supervisors report only the observed state
of their current generation through :class:`SupervisorSnapshot`.
"""

from __future__ import annotations

from dataclasses import dataclass
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
class RuntimeSnapshot:
    """Public controller-composed runtime status."""

    desired_state: DesiredRuntimeState
    state: RuntimeState
    last_error: str | None


@dataclass(frozen=True, slots=True)
class SupervisorSnapshot:
    """Observed status reported by one runtime supervisor generation."""

    state: RuntimeState
    last_error: str | None


__all__ = [
    "DesiredRuntimeState",
    "RuntimeSnapshot",
    "RuntimeState",
    "SupervisorSnapshot",
]
