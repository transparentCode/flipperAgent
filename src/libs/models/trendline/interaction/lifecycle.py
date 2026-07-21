"""Causal, persistent Phase-F interaction-event lifecycle engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Iterable, Mapping

from ..configuration.contracts import ResolvedTrendlineFamilyConfig
from ..contracts import (
    ContractValidationError,
    FamilyInteractionEvent,
    FamilyInteractionEventTransition,
    FamilyInteractionObservation,
    FamilyLifecycleState,
    FamilyRole,
    InteractionEventState,
    InteractionObservationState,
    TrendlineFamilyState,
    deterministic_id,
)
from ..events import (
    PRESSURE_EVENT_STATES,
    TERMINAL_EVENT_STATES,
    is_contact,
    is_on_broken_side,
    is_on_original_protected_side,
    is_retest_contact,
    observation_event_state,
    opposite_role,
)


@dataclass(frozen=True)
class EventLifecycleResult:
    events: tuple[FamilyInteractionEvent, ...]
    transitions: tuple[FamilyInteractionEventTransition, ...]


def pending_role_reversal_family_ids(
    events: Iterable[FamilyInteractionEvent],
) -> frozenset[str]:
    """Expose only active scheduling intents from persisted event snapshots."""

    return frozenset(
        event.family_id
        for event in events
        if event.state is InteractionEventState.RETEST_SUCCESS and event.pending_role_reversal
    )


def advance_interaction_events(
    *,
    previous_events: Iterable[FamilyInteractionEvent],
    observations: Iterable[FamilyInteractionObservation],
    families: Iterable[TrendlineFamilyState],
    timestamp: datetime,
    config: ResolvedTrendlineFamilyConfig,
    role_reversed_family_ids: frozenset[str] = frozenset(),
    deferred_role_reversal_family_ids: frozenset[str] = frozenset(),
) -> EventLifecycleResult:
    """Advance active events once from already-classified confirmed observations."""

    previous_by_family = _unique_by_family(previous_events, owner="previous interaction events")
    observations_by_family = _unique_by_family(observations, owner="interaction observations")
    result_events: list[FamilyInteractionEvent] = []
    result_transitions: list[FamilyInteractionEventTransition] = []
    for family in sorted(families, key=lambda item: item.family_id):
        previous = previous_by_family.get(family.family_id)
        observation = observations_by_family.get(family.family_id)
        if observation is None:
            raise ContractValidationError("interaction event lifecycle requires one observation per published family")
        if observation.role is not family.current_role:
            raise ContractValidationError("interaction event lifecycle observation role mismatch")
        if family.lifecycle_state is FamilyLifecycleState.DORMANT:
            # Dormancy freezes the published event before any scheduled role
            # reversal can be applied.  The tracker normally preserves the
            # old family role too; retaining the prior event here also keeps
            # the public lifecycle engine safe if it receives both signals.
            if previous is not None:
                if (
                    previous.current_event_role is not family.current_role
                    and family.family_id not in role_reversed_family_ids
                ):
                    raise ContractValidationError(
                        "dormant family cannot reverse a pending interaction event"
                    )
                result_events.append(previous)
            continue
        if previous is not None and previous.pending_role_reversal and family.family_id in role_reversed_family_ids:
            # The intent was scheduled by the prior active snapshot and is
            # applied only after this update remains active.
            event = _role_reversed_event(previous, family, observation)
            result_events.append(event)
            result_transitions.append(_transition(previous, event, observation))
            continue
        if previous is not None and previous.pending_role_reversal and family.family_id in deferred_role_reversal_family_ids:
            # A dormant previous family or a same-bar dormancy outcome keeps
            # the old role and pending intent.  It resumes on a later active
            # confirmed update rather than forcing a role reversal here.
            if previous.current_event_role is not family.current_role:
                raise ContractValidationError("deferred pending reversal must preserve the family role")
            result_events.append(previous)
            continue
        if previous is None or previous.state in TERMINAL_EVENT_STATES:
            result_events.append(_new_event(family, observation, config))
            continue
        if previous.pending_role_reversal:
            raise ContractValidationError("active pending role reversal was not applied before event advancement")
        else:
            if family.family_id in role_reversed_family_ids:
                raise ContractValidationError("role reversal was requested without a pending successful retest")
            if previous.current_event_role is not family.current_role:
                raise ContractValidationError("interaction event role changed without a pending reversal")
            event = _advance_event(previous, observation, config)
        result_events.append(event)
        if event.state is not previous.state:
            result_transitions.append(_transition(previous, event, observation))
    return EventLifecycleResult(
        events=tuple(sorted(result_events, key=lambda item: (item.family_id, item.event_id))),
        transitions=tuple(sorted(result_transitions, key=lambda item: (item.event_id, item.transition_id))),
    )


def _unique_by_family(items: Iterable[object], *, owner: str) -> Mapping[str, object]:
    values: dict[str, object] = {}
    for item in items:
        family_id = getattr(item, "family_id", None)
        if not isinstance(family_id, str):
            raise ContractValidationError(f"{owner} must contain canonical family records")
        if family_id in values:
            raise ContractValidationError(f"{owner} cannot contain duplicate family IDs")
        values[family_id] = item
    return MappingProxyType(values)


def _new_event(
    family: TrendlineFamilyState,
    observation: FamilyInteractionObservation,
    config: ResolvedTrendlineFamilyConfig,
) -> FamilyInteractionEvent:
    state = observation_event_state(observation)
    if (
        state is InteractionEventState.IN_ZONE
        and config.events.pressure_min_bars == 1
    ):
        state = InteractionEventState.PRESSURING
    close_streak = 1 if observation.state is InteractionObservationState.CLOSE_BEYOND else None
    event_id = deterministic_id(
        "family-interaction-event",
        {
            "family_id": family.family_id,
            "episode_started_at": observation.timestamp,
            "starting_role": family.current_role,
            "model_version": config.model_version,
            "config_version": config.config_version,
            "resolved_config_hash": config.resolved_config_hash,
        },
    )
    return FamilyInteractionEvent(
        event_id=event_id,
        family_id=family.family_id,
        asset=family.asset,
        timeframe=family.timeframe,
        state=state,
        started_at=observation.timestamp,
        updated_at=observation.timestamp,
        starting_role=family.current_role,
        current_event_role=family.current_role,
        previous_state=None,
        last_observation_id=observation.observation_id,
        age_bars=1,
        bars_in_state=1,
        pressure_bars=1 if is_contact(observation) else None,
        rejection_bars=None,
        close_beyond_streak=close_streak,
        retest_age_bars=None,
        retest_contact_seen=False,
        retest_confirmation_streak=None,
        retest_window_expired=False,
        role_reversal_applied=False,
        max_wick_penetration_atr=observation.wick_penetration_atr,
        max_body_penetration_atr=observation.body_penetration_atr,
        max_close_penetration_atr=observation.close_penetration_atr,
        break_pending_at=observation.timestamp if state is InteractionEventState.BREAK_PENDING else None,
        break_confirmed_at=None,
        retest_started_at=None,
        retest_succeeded_at=None,
        failed_break_at=None,
        pending_role_reversal=False,
        required_close_confirmation_bars=config.interaction.close_confirmation_bars,
        required_retest_confirmation_bars=config.events.retest_confirmation_bars,
        model_version=config.model_version,
        config_version=config.config_version,
        resolved_config_hash=config.resolved_config_hash,
        metadata={},
    )


def _role_reversed_event(
    previous: FamilyInteractionEvent,
    family: TrendlineFamilyState,
    observation: FamilyInteractionObservation,
) -> FamilyInteractionEvent:
    if family.current_role is not opposite_role(previous.starting_role):
        raise ContractValidationError("role reversal must switch to the opposite family role")
    return _event_from_previous(
        previous,
        observation,
        state=InteractionEventState.ROLE_REVERSED,
        current_event_role=family.current_role,
        pending_role_reversal=False,
        role_reversal_applied=True,
    )


def _advance_event(
    previous: FamilyInteractionEvent,
    observation: FamilyInteractionObservation,
    config: ResolvedTrendlineFamilyConfig,
) -> FamilyInteractionEvent:
    if previous.state is InteractionEventState.BREAK_CONFIRMED:
        if is_on_original_protected_side(observation, previous):
            return _event_from_previous(
                previous,
                observation,
                state=InteractionEventState.FAILED_BREAK,
                failed_break_at=observation.timestamp,
                retest_age_bars=0,
                retest_contact_seen=False,
                retest_confirmation_streak=None,
                retest_window_expired=False,
            )
        return _event_from_previous(
            previous,
            observation,
            state=InteractionEventState.RETEST_PENDING,
            retest_started_at=observation.timestamp,
            retest_age_bars=1,
            retest_contact_seen=is_retest_contact(observation, previous),
            retest_confirmation_streak=0,
        )
    if previous.state is InteractionEventState.RETEST_PENDING:
        return _advance_retest(previous, observation, config)
    if observation.state is InteractionObservationState.CLOSE_BEYOND:
        streak = (previous.close_beyond_streak or 0) + 1 if previous.state is InteractionEventState.BREAK_PENDING else 1
        if streak >= config.interaction.close_confirmation_bars:
            return _event_from_previous(
                previous,
                observation,
                state=InteractionEventState.BREAK_CONFIRMED,
                close_beyond_streak=streak,
                break_pending_at=previous.break_pending_at or observation.timestamp,
                break_confirmed_at=observation.timestamp,
                retest_contact_seen=False,
                retest_confirmation_streak=None,
                retest_window_expired=False,
            )
        return _event_from_previous(
            previous,
            observation,
            state=InteractionEventState.BREAK_PENDING,
            close_beyond_streak=streak,
            break_pending_at=previous.break_pending_at or observation.timestamp,
            retest_contact_seen=False,
            retest_confirmation_streak=None,
            retest_window_expired=False,
        )
    if observation.state in {InteractionObservationState.APPROACHING, InteractionObservationState.FAR}:
        return _advance_recovery(previous, observation, config)
    return _advance_contact(previous, observation, config)


def _advance_contact(
    previous: FamilyInteractionEvent,
    observation: FamilyInteractionObservation,
    config: ResolvedTrendlineFamilyConfig,
) -> FamilyInteractionEvent:
    pressure = (previous.pressure_bars or 0) + 1 if previous.state in PRESSURE_EVENT_STATES else 1
    if observation.state is InteractionObservationState.IN_ZONE:
        state = InteractionEventState.PRESSURING if pressure >= config.events.pressure_min_bars else InteractionEventState.IN_ZONE
    elif observation.state is InteractionObservationState.WICK_BREACH:
        state = InteractionEventState.WICK_BREACHED
    else:
        state = InteractionEventState.BODY_BREACHED
    return _event_from_previous(
        previous,
        observation,
        state=state,
        pressure_bars=pressure,
        rejection_bars=None,
        close_beyond_streak=None,
        break_pending_at=None,
        retest_contact_seen=False,
        retest_confirmation_streak=None,
        retest_window_expired=False,
    )


def _advance_recovery(
    previous: FamilyInteractionEvent,
    observation: FamilyInteractionObservation,
    config: ResolvedTrendlineFamilyConfig,
) -> FamilyInteractionEvent:
    if previous.state in PRESSURE_EVENT_STATES | {InteractionEventState.BREAK_PENDING}:
        state = (
            observation_event_state(observation)
            if config.events.rejection_recovery_bars == 1
            else InteractionEventState.REJECTING
        )
        return _event_from_previous(
            previous,
            observation,
            state=state,
            rejection_bars=1,
            close_beyond_streak=None,
            break_pending_at=None,
            retest_contact_seen=False,
            retest_confirmation_streak=None,
            retest_window_expired=False,
        )
    if previous.state is InteractionEventState.REJECTING:
        rejection = (previous.rejection_bars or 0) + 1
        state = (
            observation_event_state(observation)
            if rejection >= config.events.rejection_recovery_bars
            else InteractionEventState.REJECTING
        )
        return _event_from_previous(
            previous,
            observation,
            state=state,
            rejection_bars=rejection,
            close_beyond_streak=None,
            break_pending_at=None,
            retest_contact_seen=False,
            retest_confirmation_streak=None,
            retest_window_expired=False,
        )
    return _event_from_previous(
        previous,
        observation,
        state=observation_event_state(observation),
        pressure_bars=None,
        rejection_bars=None,
        close_beyond_streak=None,
        break_pending_at=None,
        retest_contact_seen=False,
        retest_confirmation_streak=None,
        retest_window_expired=False,
    )


def _advance_retest(
    previous: FamilyInteractionEvent,
    observation: FamilyInteractionObservation,
    config: ResolvedTrendlineFamilyConfig,
) -> FamilyInteractionEvent:
    age = (previous.retest_age_bars or 0) + 1
    if is_on_original_protected_side(observation, previous):
        return _event_from_previous(
            previous,
            observation,
            state=InteractionEventState.FAILED_BREAK,
            failed_break_at=observation.timestamp,
            retest_age_bars=None,
            retest_contact_seen=False,
            retest_confirmation_streak=None,
            retest_window_expired=False,
        )
    contact_seen = previous.retest_contact_seen or is_retest_contact(observation, previous)
    streak = previous.retest_confirmation_streak or 0
    if contact_seen and is_on_broken_side(observation, previous):
        streak += 1
        if streak >= config.events.retest_confirmation_bars:
            return _event_from_previous(
                previous,
                observation,
                state=InteractionEventState.RETEST_SUCCESS,
                retest_age_bars=age,
                retest_succeeded_at=observation.timestamp,
                pending_role_reversal=True,
                retest_contact_seen=contact_seen,
                retest_confirmation_streak=streak,
            )
    elif observation.state is not InteractionObservationState.CLOSE_BEYOND:
        streak = 0
    if age >= config.events.retest_window_bars:
        # Expiry is a non-promotional resolution: retain the family role and
        # resolve evidence to FAR rather than inferring a successful retest.
        return _event_from_previous(
            previous,
            observation,
            state=InteractionEventState.FAR,
            retest_age_bars=None,
            retest_contact_seen=False,
            retest_confirmation_streak=None,
            retest_window_expired=True,
        )
    return _event_from_previous(
        previous,
        observation,
        state=InteractionEventState.RETEST_PENDING,
        retest_age_bars=age,
        retest_contact_seen=contact_seen,
        retest_confirmation_streak=streak,
    )


def _event_from_previous(
    previous: FamilyInteractionEvent,
    observation: FamilyInteractionObservation,
    *,
    state: InteractionEventState,
    current_event_role: FamilyRole | None = None,
    pressure_bars: int | None | object = ...,
    rejection_bars: int | None | object = ...,
    close_beyond_streak: int | None | object = ...,
    retest_age_bars: int | None | object = ...,
    retest_contact_seen: bool | object = ...,
    retest_confirmation_streak: int | None | object = ...,
    retest_window_expired: bool | object = ...,
    role_reversal_applied: bool | object = ...,
    break_pending_at: datetime | None | object = ...,
    break_confirmed_at: datetime | None | object = ...,
    retest_started_at: datetime | None | object = ...,
    retest_succeeded_at: datetime | None | object = ...,
    failed_break_at: datetime | None | object = ...,
    pending_role_reversal: bool | None = None,
    metadata: Mapping[str, object] | None = None,
) -> FamilyInteractionEvent:
    # ``...`` is the internal unchanged sentinel, preserving ``None`` as a
    # meaningful reset value for optional timestamps and counters.
    def choose(value: object, current: object) -> object:
        return current if value is ... else value  # type: ignore[return-value]
    return FamilyInteractionEvent(
        event_id=previous.event_id,
        family_id=previous.family_id,
        asset=previous.asset,
        timeframe=previous.timeframe,
        state=state,
        started_at=previous.started_at,
        updated_at=observation.timestamp,
        starting_role=previous.starting_role,
        current_event_role=previous.current_event_role if current_event_role is None else current_event_role,
        previous_state=previous.state,
        last_observation_id=observation.observation_id,
        age_bars=previous.age_bars + 1,
        bars_in_state=previous.bars_in_state + 1 if state is previous.state else 1,
        pressure_bars=choose(pressure_bars, previous.pressure_bars),
        rejection_bars=choose(rejection_bars, previous.rejection_bars),
        close_beyond_streak=choose(close_beyond_streak, previous.close_beyond_streak),
        retest_age_bars=choose(retest_age_bars, previous.retest_age_bars),
        retest_contact_seen=choose(retest_contact_seen, previous.retest_contact_seen),
        retest_confirmation_streak=choose(
            retest_confirmation_streak,
            previous.retest_confirmation_streak,
        ),
        retest_window_expired=choose(
            retest_window_expired,
            previous.retest_window_expired,
        ),
        role_reversal_applied=choose(
            role_reversal_applied,
            previous.role_reversal_applied,
        ),
        max_wick_penetration_atr=max(previous.max_wick_penetration_atr, observation.wick_penetration_atr),
        max_body_penetration_atr=max(previous.max_body_penetration_atr, observation.body_penetration_atr),
        max_close_penetration_atr=max(previous.max_close_penetration_atr, observation.close_penetration_atr),
        break_pending_at=choose(break_pending_at, previous.break_pending_at),
        break_confirmed_at=choose(break_confirmed_at, previous.break_confirmed_at),
        retest_started_at=choose(retest_started_at, previous.retest_started_at),
        retest_succeeded_at=choose(retest_succeeded_at, previous.retest_succeeded_at),
        failed_break_at=choose(failed_break_at, previous.failed_break_at),
        pending_role_reversal=previous.pending_role_reversal if pending_role_reversal is None else pending_role_reversal,
        required_close_confirmation_bars=previous.required_close_confirmation_bars,
        required_retest_confirmation_bars=previous.required_retest_confirmation_bars,
        model_version=previous.model_version,
        config_version=previous.config_version,
        resolved_config_hash=previous.resolved_config_hash,
        metadata=previous.metadata if metadata is None else metadata,
    )


def _transition(
    previous: FamilyInteractionEvent,
    event: FamilyInteractionEvent,
    observation: FamilyInteractionObservation,
) -> FamilyInteractionEventTransition:
    payload = {
        "event_id": event.event_id,
        "family_id": event.family_id,
        "from_state": previous.state,
        "to_state": event.state,
        "timestamp": event.updated_at,
        "trigger_observation_id": observation.observation_id,
        "reason_code": f"observation_{observation.state.value.lower()}",
        "bars_in_previous_state": previous.bars_in_state,
        "metrics": {
            "pressure_bars": float(event.pressure_bars or 0),
            "close_beyond_streak": float(event.close_beyond_streak or 0),
            "retest_age_bars": float(event.retest_age_bars or 0),
            "max_close_penetration_atr": event.max_close_penetration_atr,
        },
        "model_version": event.model_version,
        "config_version": event.config_version,
        "resolved_config_hash": event.resolved_config_hash,
    }
    return FamilyInteractionEventTransition(
        transition_id=deterministic_id("family-interaction-event-transition", {"transition": payload, "event": event.to_dict()}),
        **payload,
    )
