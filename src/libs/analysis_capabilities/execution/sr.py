"""Thin state-threading execution adapter for the canonical SR model."""

from dataclasses import dataclass

from libs.models.sr import (
    ClosedBar,
    ResolvedSRConfig,
    SREngine,
    SREvent,
    SRSnapshot,
    SRState,
)


@dataclass(frozen=True, slots=True)
class SRExecutionRequest:
    """One explicit SR step and all of its caller-owned native inputs."""

    previous_state: SRState
    closed_bar: ClosedBar
    resolved_config: ResolvedSRConfig


@dataclass(frozen=True, slots=True)
class SRExecutionResult:
    """The native SR step outputs without serialization or projection."""

    next_state: SRState
    snapshot: SRSnapshot
    events: tuple[SREvent, ...]


def execute_sr(request: SRExecutionRequest) -> SRExecutionResult:
    """Apply exactly one explicit SR state transition."""

    if not isinstance(request, SRExecutionRequest):
        raise TypeError("request must be SRExecutionRequest")
    next_state, snapshot, events = SREngine().step(
        request.previous_state,
        request.closed_bar,
        request.resolved_config,
    )
    return SRExecutionResult(
        next_state=next_state,
        snapshot=snapshot,
        events=events,
    )


__all__ = ("SRExecutionRequest", "SRExecutionResult", "execute_sr")
