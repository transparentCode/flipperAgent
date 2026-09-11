"""Typed lifecycle transition contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum

from ..contracts import LifecycleState, require_utc
from ..domain.identity import canonical_hash


class TransitionType(str, Enum):
    CREATED = "CREATED"
    TOUCH_STARTED = "TOUCH_STARTED"
    TOUCH_ENDED = "TOUCH_ENDED"
    BREAK_PENDING = "BREAK_PENDING"
    BREAK_CLEARED = "BREAK_CLEARED"
    BROKEN = "BROKEN"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    TOMBSTONE_PRUNED = "TOMBSTONE_PRUNED"


@dataclass(frozen=True, slots=True, kw_only=True)
class LifecycleTransition:
    """One normalized structural mutation in deterministic core order."""

    transition_id: str
    ordinal: int
    transition_type: TransitionType
    event_at: datetime
    zone_id: str
    before_lifecycle: LifecycleState | None
    after_lifecycle: LifecycleState | None
    before_overlapping: bool
    after_overlapping: bool
    before_touch_count: int
    after_touch_count: int
    before_break_pending_count: int
    after_break_pending_count: int
    retention_state: str
    causal_bar_id: str | None = None
    predecessor_id: str | None = None
    successor_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.transition_id, str) or not self.transition_id.strip():
            raise ValueError("transition_id must be non-empty")
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")
        if not isinstance(self.transition_type, TransitionType):
            raise TypeError("transition_type must be TransitionType")
        require_utc(self.event_at, field_name="event_at")
        if not isinstance(self.zone_id, str) or not self.zone_id.strip():
            raise ValueError("zone_id must be non-empty")
        for name in ("before_lifecycle", "after_lifecycle"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, LifecycleState):
                raise TypeError(f"{name} must be LifecycleState or None")
        for name in ("before_overlapping", "after_overlapping"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be bool")
        for name in ("before_touch_count", "after_touch_count", "before_break_pending_count", "after_break_pending_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.retention_state, str) or not self.retention_state.strip():
            raise ValueError("retention_state must be non-empty")
        for name in ("causal_bar_id", "predecessor_id", "successor_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be non-empty when supplied")

    def with_ordinal(self, ordinal: int) -> LifecycleTransition:
        return replace(self, ordinal=ordinal)

def make_transition(
    *,
    transition_type: TransitionType,
    event_at: datetime,
    zone_id: str,
    before_lifecycle: LifecycleState | None,
    after_lifecycle: LifecycleState | None,
    before_overlapping: bool,
    after_overlapping: bool,
    before_touch_count: int,
    after_touch_count: int,
    before_break_pending_count: int,
    after_break_pending_count: int,
    retention_state: str,
    causal_bar_id: str | None = None,
    predecessor_id: str | None = None,
    successor_id: str | None = None,
) -> LifecycleTransition:
    identity = {
        "transition_type": transition_type.value,
        "event_at": event_at,
        "zone_id": zone_id,
        "before_lifecycle": before_lifecycle,
        "after_lifecycle": after_lifecycle,
        "before_overlapping": before_overlapping,
        "after_overlapping": after_overlapping,
        "before_touch_count": before_touch_count,
        "after_touch_count": after_touch_count,
        "before_break_pending_count": before_break_pending_count,
        "after_break_pending_count": after_break_pending_count,
        "retention_state": retention_state,
        "causal_bar_id": causal_bar_id,
        "predecessor_id": predecessor_id,
        "successor_id": successor_id,
    }
    return LifecycleTransition(
        transition_id=canonical_hash(identity),
        ordinal=0,
        transition_type=transition_type,
        event_at=event_at,
        zone_id=zone_id,
        before_lifecycle=before_lifecycle,
        after_lifecycle=after_lifecycle,
        before_overlapping=before_overlapping,
        after_overlapping=after_overlapping,
        before_touch_count=before_touch_count,
        after_touch_count=after_touch_count,
        before_break_pending_count=before_break_pending_count,
        after_break_pending_count=after_break_pending_count,
        retention_state=retention_state,
        causal_bar_id=causal_bar_id,
        predecessor_id=predecessor_id,
        successor_id=successor_id,
    )


__all__ = ["LifecycleTransition", "TransitionType", "make_transition"]
