"""Canonical immutable event records re-exported without semantic changes."""

from __future__ import annotations

from ..contracts import (
    FamilyInteractionEvent,
    FamilyInteractionEventTransition,
    FamilyTransition,
)

# Interaction events are model event episodes. Family transitions remain a
# separate persisted lifecycle record and are exposed alongside them.
TrendlineEvent = FamilyInteractionEvent
TrendlineEventTransition = FamilyInteractionEventTransition

__all__ = [
    "FamilyTransition",
    "TrendlineEvent",
    "TrendlineEventTransition",
]
