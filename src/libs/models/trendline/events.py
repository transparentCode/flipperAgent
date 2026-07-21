"""Phase-F event-state vocabulary and deterministic transition policy.

This module owns event-state decisions.  It consumes only persisted Phase-D
observation fields; it never reads OHLCV or recreates zones/classification.
"""

from __future__ import annotations

from .domain.events import is_allowed_event_transition as is_allowed_event_transition
from .contracts import (
    FamilyInteractionEvent,
    FamilyInteractionObservation,
    FamilyRole,
    InteractionCompatibilityLabel,
    InteractionEventState,
    InteractionObservationState,
)


CONTACT_OBSERVATION_STATES = frozenset(
    {
        InteractionObservationState.IN_ZONE,
        InteractionObservationState.WICK_BREACH,
        InteractionObservationState.BODY_BREACH,
    }
)
PRESSURE_EVENT_STATES = frozenset(
    {
        InteractionEventState.IN_ZONE,
        InteractionEventState.PRESSURING,
        InteractionEventState.WICK_BREACHED,
        InteractionEventState.BODY_BREACHED,
    }
)
TERMINAL_EVENT_STATES = frozenset(
    {
        InteractionEventState.FAILED_BREAK,
        InteractionEventState.ROLE_REVERSED,
    }
)

def opposite_role(role: FamilyRole) -> FamilyRole:
    """Return the causal role after a confirmed break/retest reversal."""

    if role is FamilyRole.SUPPORT:
        return FamilyRole.RESISTANCE
    if role is FamilyRole.RESISTANCE:
        return FamilyRole.SUPPORT
    raise ValueError("interaction events require SUPPORT or RESISTANCE")


def observation_event_state(observation: FamilyInteractionObservation) -> InteractionEventState:
    """Map one immutable Phase-D observation to its base event state."""

    mapping = {
        InteractionObservationState.FAR: InteractionEventState.FAR,
        InteractionObservationState.APPROACHING: InteractionEventState.APPROACHING,
        InteractionObservationState.IN_ZONE: InteractionEventState.IN_ZONE,
        InteractionObservationState.WICK_BREACH: InteractionEventState.WICK_BREACHED,
        InteractionObservationState.BODY_BREACH: InteractionEventState.BODY_BREACHED,
        InteractionObservationState.CLOSE_BEYOND: InteractionEventState.BREAK_PENDING,
    }
    return mapping[observation.state]


def is_contact(observation: FamilyInteractionObservation) -> bool:
    return observation.state in CONTACT_OBSERVATION_STATES


def is_on_original_protected_side(
    observation: FamilyInteractionObservation,
    event: FamilyInteractionEvent,
) -> bool:
    """Detect a causal failed break from the persisted confirmed close price."""

    close = observation.close_price
    if close is None:
        return False
    if event.starting_role is FamilyRole.SUPPORT:
        return close >= observation.zone.upper_price
    return close <= observation.zone.lower_price


def is_on_broken_side(
    observation: FamilyInteractionObservation,
    event: FamilyInteractionEvent,
) -> bool:
    """Require a retest confirmation close on the expected post-break side."""

    close = observation.close_price
    if close is None:
        return False
    if event.starting_role is FamilyRole.SUPPORT:
        return close < observation.zone.lower_price
    return close > observation.zone.upper_price


def is_retest_contact(
    observation: FamilyInteractionObservation,
    event: FamilyInteractionEvent,
) -> bool:
    """Require contact to arrive from the side created by the confirmed break."""

    if not is_contact(observation) or observation.close_price is None:
        return False
    if event.starting_role is FamilyRole.SUPPORT:
        return observation.close_price <= observation.zone.center_price
    return observation.close_price >= observation.zone.center_price


def compatibility_label(
    event: FamilyInteractionEvent,
) -> InteractionCompatibilityLabel | None:
    """Project stable labels from persisted state without changing policy."""

    if event.state in {
        InteractionEventState.BREAK_CONFIRMED,
        InteractionEventState.RETEST_PENDING,
        InteractionEventState.RETEST_SUCCESS,
    }:
        return (
            InteractionCompatibilityLabel.BREAKDOWN
            if event.starting_role is FamilyRole.SUPPORT
            else InteractionCompatibilityLabel.BREAKOUT
        )
    if event.state is InteractionEventState.REJECTING:
        return (
            InteractionCompatibilityLabel.BOUNCE
            if event.current_event_role is FamilyRole.SUPPORT
            else InteractionCompatibilityLabel.REJECTION
        )
    return None
