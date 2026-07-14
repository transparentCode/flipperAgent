"""Phase-F persistent interaction-event lifecycle tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from libs.models.trendline_family.contracts import (
    ContractValidationError,
    FamilyLifecycleState,
    FamilyRole,
    InteractionEventState,
    TrendlineFamilySnapshot,
)
from libs.models.trendline_family.event_lifecycle import (
    advance_interaction_events,
    pending_role_reversal_family_ids,
)
from libs.models.trendline_family.events import compatibility_label
from libs.models.trendline_family.interactions import InteractionAtr, evaluate_family_interaction
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository
from libs.models.trendline_family.tracker import TrendlineFamilyTracker

from .tracker_support import (
    SequenceProvider,
    abstention,
    candidate,
    interaction_family,
    legacy_pre_phase_g_payload,
    timestamp,
    tracker_config,
    tracker_ohlcv,
    valid_result,
)


def _observation(family, config, hour: int, kind: str):
    candles = {
        "far": (102.0, 103.0, 102.0, 102.0),
        "far_below": (98.4, 98.5, 98.0, 98.2),
        "approaching": (100.8, 100.9, 100.5, 100.6),
        "in_zone_support": (99.9, 100.1, 99.8, 99.9),
        "in_zone_resistance": (100.1, 100.2, 99.9, 100.1),
        "wick_support": (100.0, 100.1, 99.5, 100.0),
        "body_support": (99.6, 100.0, 99.5, 100.0),
        "close_beyond_support": (99.6, 100.0, 99.4, 99.5),
        "close_beyond_resistance": (100.4, 100.6, 100.0, 100.5),
        "failed_support": (100.2, 100.6, 100.1, 100.5),
        "failed_resistance": (99.8, 99.9, 99.4, 99.5),
    }
    candle = candles[kind]
    return evaluate_family_interaction(
        family,
        timestamp=timestamp(hour),
        open_price=candle[0],
        high_price=candle[1],
        low_price=candle[2],
        close_price=candle[3],
        interaction_atr=InteractionAtr(1.0, "simple_true_range_mean_v1", 3),
        config=config,
        tick_size=None,
    ).observation


def _advance(
    previous,
    family,
    observation,
    config,
    *,
    reversed_ids=frozenset(),
    deferred_ids=frozenset(),
):
    return advance_interaction_events(
        previous_events=() if previous is None else (previous,),
        observations=(observation,),
        families=(family,),
        timestamp=observation.timestamp,
        config=config,
        role_reversed_family_ids=reversed_ids,
        deferred_role_reversal_family_ids=deferred_ids,
    ).events[0]


def _break_transition_snapshots():
    config = tracker_config()
    first_time, second_time = timestamp(), timestamp(1)
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider(
            (
                valid_result(candidate(config, first_time, candidate_id="first-break")),
                valid_result(candidate(config, second_time, candidate_id="second-break")),
            )
        ),
        config=config,
    )
    snapshots = []
    for observed in (first_time, second_time):
        frame = tracker_ohlcv(observed)
        frame.iloc[-1] = (99.4, 100.0, 98.8, 99.0)
        snapshots.append(tracker.update(frame).snapshot)
    return tuple(snapshots)


def test_consecutive_closes_are_required_for_break_confirmation() -> None:
    config = tracker_config(interaction={"close_confirmation_bars": 2})
    family = interaction_family(config, timestamp(), role=FamilyRole.SUPPORT)
    first = _advance(None, family, _observation(family, config, 0, "close_beyond_support"), config)
    assert first.state is InteractionEventState.BREAK_PENDING
    assert first.close_beyond_streak == 1

    interrupted = _advance(first, family, _observation(family, config, 1, "in_zone_support"), config)
    assert interrupted.state is InteractionEventState.IN_ZONE
    assert interrupted.close_beyond_streak is None

    pending = _advance(interrupted, family, _observation(family, config, 2, "close_beyond_support"), config)
    confirmed = _advance(pending, family, _observation(family, config, 3, "close_beyond_support"), config)
    assert confirmed.state is InteractionEventState.BREAK_CONFIRMED
    assert confirmed.break_confirmed_at == timestamp(3)


def test_pressure_rejection_and_recovery_are_configured() -> None:
    config = tracker_config(events={"pressure_min_bars": 2, "rejection_recovery_bars": 2})
    family = interaction_family(config, timestamp(), role=FamilyRole.SUPPORT)
    in_zone = _advance(None, family, _observation(family, config, 0, "in_zone_support"), config)
    pressuring = _advance(in_zone, family, _observation(family, config, 1, "in_zone_support"), config)
    rejecting = _advance(pressuring, family, _observation(family, config, 2, "approaching"), config)
    recovered = _advance(rejecting, family, _observation(family, config, 3, "far"), config)
    assert pressuring.state is InteractionEventState.PRESSURING
    assert pressuring.pressure_bars == 2
    assert rejecting.state is InteractionEventState.REJECTING
    assert recovered.state is InteractionEventState.FAR


def test_retest_success_schedules_then_applies_same_event_role_reversal() -> None:
    config = tracker_config(events={"retest_confirmation_bars": 1})
    family = interaction_family(config, timestamp(), role=FamilyRole.SUPPORT)
    pending = _advance(None, family, _observation(family, config, 0, "close_beyond_support"), config)
    confirmed = _advance(pending, family, _observation(family, config, 1, "close_beyond_support"), config)
    retest = _advance(confirmed, family, _observation(family, config, 2, "in_zone_support"), config)
    success = _advance(retest, family, _observation(family, config, 3, "close_beyond_support"), config)
    assert success.state is InteractionEventState.RETEST_SUCCESS
    assert success.pending_role_reversal is True
    assert pending_role_reversal_family_ids((success,)) == frozenset({family.family_id})

    reversed_family = replace(
        family,
        current_role=FamilyRole.RESISTANCE,
        members=(replace(family.members[0], role=FamilyRole.RESISTANCE),),
    )
    reversed_event = _advance(
        success,
        reversed_family,
        _observation(reversed_family, config, 4, "in_zone_resistance"),
        config,
        reversed_ids=frozenset({family.family_id}),
    )
    assert reversed_event.event_id == success.event_id
    assert reversed_event.state is InteractionEventState.ROLE_REVERSED
    assert reversed_event.current_event_role is FamilyRole.RESISTANCE
    assert reversed_event.pending_role_reversal is False


def test_resistance_role_reversal_is_mirrored() -> None:
    config = tracker_config(events={"retest_confirmation_bars": 1})
    family = interaction_family(config, timestamp(), role=FamilyRole.RESISTANCE)
    pending = _advance(None, family, _observation(family, config, 0, "close_beyond_resistance"), config)
    confirmed = _advance(pending, family, _observation(family, config, 1, "close_beyond_resistance"), config)
    retest = _advance(confirmed, family, _observation(family, config, 2, "in_zone_resistance"), config)
    success = _advance(retest, family, _observation(family, config, 3, "close_beyond_resistance"), config)
    reversed_family = replace(
        family,
        current_role=FamilyRole.SUPPORT,
        members=(replace(family.members[0], role=FamilyRole.SUPPORT),),
    )
    reversed_event = _advance(
        success,
        reversed_family,
        _observation(reversed_family, config, 4, "in_zone_support"),
        config,
        reversed_ids=frozenset({family.family_id}),
    )
    assert reversed_event.state is InteractionEventState.ROLE_REVERSED
    assert reversed_event.current_event_role is FamilyRole.SUPPORT


def test_retest_window_expiry_resolves_to_far_without_role_reversal() -> None:
    config = tracker_config(events={"retest_window_bars": 2})
    family = interaction_family(config, timestamp(), role=FamilyRole.SUPPORT)
    pending = _advance(None, family, _observation(family, config, 0, "close_beyond_support"), config)
    confirmed = _advance(pending, family, _observation(family, config, 1, "close_beyond_support"), config)
    retest = _advance(confirmed, family, _observation(family, config, 2, "far_below"), config)
    expired = _advance(retest, family, _observation(family, config, 3, "far_below"), config)
    assert retest.state is InteractionEventState.RETEST_PENDING
    assert expired.state is InteractionEventState.FAR
    assert expired.pending_role_reversal is False
    assert expired.retest_window_expired is True


def test_pending_reversal_freezes_while_dormant_then_resumes_after_reactivation() -> None:
    config = tracker_config(events={"retest_confirmation_bars": 1})
    family = interaction_family(config, timestamp(), role=FamilyRole.SUPPORT)
    pending = _advance(None, family, _observation(family, config, 0, "close_beyond_support"), config)
    confirmed = _advance(pending, family, _observation(family, config, 1, "close_beyond_support"), config)
    retest = _advance(confirmed, family, _observation(family, config, 2, "in_zone_support"), config)
    success = _advance(retest, family, _observation(family, config, 3, "close_beyond_support"), config)
    assert success.pending_role_reversal is True

    dormant = replace(family, lifecycle_state=FamilyLifecycleState.DORMANT)
    frozen = _advance(
        success,
        dormant,
        _observation(dormant, config, 4, "far"),
        config,
        deferred_ids=frozenset({family.family_id}),
    )
    assert frozen == success

    reactivated = replace(family, lifecycle_state=FamilyLifecycleState.ACTIVE)
    deferred = _advance(
        frozen,
        reactivated,
        _observation(reactivated, config, 5, "in_zone_support"),
        config,
        deferred_ids=frozenset({family.family_id}),
    )
    assert deferred == success

    reversed_family = replace(
        reactivated,
        current_role=FamilyRole.RESISTANCE,
        members=(replace(reactivated.members[0], role=FamilyRole.RESISTANCE),),
    )
    resumed = _advance(
        deferred,
        reversed_family,
        _observation(reversed_family, config, 6, "in_zone_resistance"),
        config,
        reversed_ids=frozenset({family.family_id}),
    )
    assert resumed.state is InteractionEventState.ROLE_REVERSED


@pytest.mark.parametrize(
    ("role", "close_kind", "contact_kind", "reversed_role", "reversed_contact_kind"),
    (
        (
            FamilyRole.SUPPORT,
            "close_beyond_support",
            "in_zone_support",
            FamilyRole.RESISTANCE,
            "in_zone_resistance",
        ),
        (
            FamilyRole.RESISTANCE,
            "close_beyond_resistance",
            "in_zone_resistance",
            FamilyRole.SUPPORT,
            "in_zone_support",
        ),
    ),
)
def test_dormant_lifecycle_defers_requested_role_reversal(
    role,
    close_kind,
    contact_kind,
    reversed_role,
    reversed_contact_kind,
) -> None:
    config = tracker_config(events={"retest_confirmation_bars": 1})
    family = interaction_family(config, timestamp(), role=role)
    pending = _advance(None, family, _observation(family, config, 0, close_kind), config)
    confirmed = _advance(pending, family, _observation(family, config, 1, close_kind), config)
    retest = _advance(confirmed, family, _observation(family, config, 2, contact_kind), config)
    success = _advance(retest, family, _observation(family, config, 3, close_kind), config)
    reversed_dormant_family = replace(
        family,
        lifecycle_state=FamilyLifecycleState.DORMANT,
        current_role=reversed_role,
        members=(replace(family.members[0], role=reversed_role),),
    )

    result = advance_interaction_events(
        previous_events=(success,),
        observations=(
            _observation(
                reversed_dormant_family,
                config,
                4,
                reversed_contact_kind,
            ),
        ),
        families=(reversed_dormant_family,),
        timestamp=timestamp(4),
        config=config,
        role_reversed_family_ids=frozenset({family.family_id}),
    )

    assert result.events == (success,)
    assert result.transitions == ()


def test_minimum_pressure_and_recovery_thresholds_apply_on_entry() -> None:
    config = tracker_config(events={"pressure_min_bars": 1, "rejection_recovery_bars": 1})
    family = interaction_family(config, timestamp())
    pressuring = _advance(None, family, _observation(family, config, 0, "in_zone_support"), config)
    recovered = _advance(pressuring, family, _observation(family, config, 1, "approaching"), config)
    assert pressuring.state is InteractionEventState.PRESSURING
    assert recovered.state is InteractionEventState.APPROACHING


def test_retest_window_requires_contact_and_confirmation_capacity() -> None:
    with pytest.raises(ContractValidationError, match="retest_window_bars must be at least 2"):
        tracker_config(events={"retest_window_bars": 1})


def test_forged_post_break_event_histories_fail_contract_validation() -> None:
    config = tracker_config(events={"retest_confirmation_bars": 1})
    family = interaction_family(config, timestamp())
    pending = _advance(None, family, _observation(family, config, 0, "close_beyond_support"), config)
    confirmed = _advance(pending, family, _observation(family, config, 1, "close_beyond_support"), config)
    retest = _advance(confirmed, family, _observation(family, config, 2, "in_zone_support"), config)
    success = _advance(retest, family, _observation(family, config, 3, "close_beyond_support"), config)
    reversed_family = replace(
        family,
        current_role=FamilyRole.RESISTANCE,
        members=(replace(family.members[0], role=FamilyRole.RESISTANCE),),
    )
    reversed_event = _advance(
        success,
        reversed_family,
        _observation(reversed_family, config, 4, "in_zone_resistance"),
        config,
        reversed_ids=frozenset({family.family_id}),
    )

    with pytest.raises(ContractValidationError, match="BREAK_PENDING predecessor"):
        replace(confirmed, previous_state=InteractionEventState.FAR)
    with pytest.raises(ContractValidationError, match="typed confirmed retest"):
        replace(success, retest_confirmation_streak=0)
    with pytest.raises(ContractValidationError, match="successful pending retest"):
        replace(reversed_event, previous_state=InteractionEventState.FAR)


def test_snapshot_binds_current_event_transition_to_event_and_observation() -> None:
    _, snapshot = _break_transition_snapshots()
    first_time = timestamp()
    transition = snapshot.interaction_event_transitions[0]

    with pytest.raises(ContractValidationError, match="source must match"):
        replace(
            snapshot,
            interaction_event_transitions=(
                replace(transition, from_state=InteractionEventState.FAR),
            ),
        )
    with pytest.raises(ContractValidationError, match="timestamp must match"):
        replace(
            snapshot,
            interaction_event_transitions=(replace(transition, timestamp=first_time),),
        )
    with pytest.raises(ContractValidationError, match="observation"):
        replace(
            snapshot,
            interaction_event_transitions=(
                replace(transition, trigger_observation_id="other-observation"),
            ),
        )


def test_snapshot_requires_one_transition_for_each_current_event_state_change() -> None:
    new_episode, changed_snapshot = _break_transition_snapshots()
    transition = changed_snapshot.interaction_event_transitions[0]

    assert new_episode.interaction_events[0].previous_state is None
    assert new_episode.interaction_event_transitions == ()
    with pytest.raises(ContractValidationError, match="exactly one transition"):
        replace(changed_snapshot, interaction_event_transitions=())

    duplicate = replace(transition, transition_id=f"0-{transition.transition_id}")
    transitions = tuple(
        sorted(
            (transition, duplicate),
            key=lambda item: (item.event_id, item.transition_id),
        )
    )
    with pytest.raises(ContractValidationError, match="exactly one transition"):
        replace(changed_snapshot, interaction_event_transitions=transitions)


def test_event_transition_requires_persisted_close_evidence_and_replays() -> None:
    _, snapshot = _break_transition_snapshots()
    observation = snapshot.observations[0]

    assert TrendlineFamilySnapshot.from_dict(snapshot.to_dict()) == snapshot
    with pytest.raises(ContractValidationError, match="event transition requires persisted close_price"):
        replace(snapshot, observations=(replace(observation, close_price=None),))


def test_snapshot_rejects_transition_for_an_unchanged_or_frozen_event() -> None:
    config = tracker_config(interaction={"close_confirmation_bars": 3})
    first_time, second_time = timestamp(), timestamp(1)
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider(
            (
                valid_result(candidate(config, first_time, candidate_id="unchanged-first")),
                valid_result(candidate(config, second_time, candidate_id="unchanged-second")),
            )
        ),
        config=config,
    )
    for observed in (first_time, second_time):
        frame = tracker_ohlcv(observed)
        frame.iloc[-1] = (99.4, 100.0, 98.8, 99.0)
        unchanged_snapshot = tracker.update(frame).snapshot
    unchanged_event = unchanged_snapshot.interaction_events[0]
    _, changed_snapshot = _break_transition_snapshots()
    template = changed_snapshot.interaction_event_transitions[0]
    forged_unchanged = replace(
        template,
        event_id=unchanged_event.event_id,
        family_id=unchanged_event.family_id,
        from_state=InteractionEventState.IN_ZONE,
        to_state=unchanged_event.state,
        timestamp=unchanged_snapshot.timestamp,
        trigger_observation_id=unchanged_event.last_observation_id,
    )

    assert unchanged_event.previous_state is unchanged_event.state
    assert unchanged_snapshot.interaction_event_transitions == ()
    with pytest.raises(ContractValidationError, match="unchanged interaction event"):
        replace(
            unchanged_snapshot,
            interaction_event_transitions=(forged_unchanged,),
        )


def test_compatibility_labels_are_pure_role_mirrored_event_projections() -> None:
    config = tracker_config()
    support = interaction_family(config, timestamp(), role=FamilyRole.SUPPORT)
    support_pending = _advance(
        None,
        support,
        _observation(support, config, 0, "close_beyond_support"),
        config,
    )
    resistance = interaction_family(config, timestamp(), role=FamilyRole.RESISTANCE)
    resistance_pending = _advance(
        None,
        resistance,
        _observation(resistance, config, 0, "close_beyond_resistance"),
        config,
    )
    assert compatibility_label(support_pending) is None
    assert compatibility_label(resistance_pending) is None

    support_confirmed = _advance(
        support_pending,
        support,
        _observation(support, config, 1, "close_beyond_support"),
        config,
    )
    resistance_confirmed = _advance(
        resistance_pending,
        resistance,
        _observation(resistance, config, 1, "close_beyond_resistance"),
        config,
    )
    assert compatibility_label(support_confirmed).value == "breakdown"
    assert compatibility_label(resistance_confirmed).value == "breakout"

    support_failed = _advance(
        support_confirmed,
        support,
        _observation(support, config, 2, "failed_support"),
        config,
    )
    assert support_failed.state is InteractionEventState.FAILED_BREAK
    assert compatibility_label(support_failed) is None


@pytest.mark.parametrize(
    ("role", "first_close", "failed_close"),
    (
        (FamilyRole.SUPPORT, "close_beyond_support", "failed_support"),
        (FamilyRole.RESISTANCE, "close_beyond_resistance", "failed_resistance"),
    ),
)
def test_failed_break_is_role_mirrored_and_causal(role, first_close, failed_close) -> None:
    config = tracker_config()
    family = interaction_family(config, timestamp(), role=role)
    pending = _advance(None, family, _observation(family, config, 0, first_close), config)
    confirmed = _advance(pending, family, _observation(family, config, 1, first_close), config)
    failed = _advance(confirmed, family, _observation(family, config, 2, failed_close), config)
    assert failed.state is InteractionEventState.FAILED_BREAK
    assert failed.failed_break_at == timestamp(2)


def test_terminal_event_starts_a_new_deterministic_episode() -> None:
    config = tracker_config()
    family = interaction_family(config, timestamp())
    pending = _advance(None, family, _observation(family, config, 0, "close_beyond_support"), config)
    confirmed = _advance(pending, family, _observation(family, config, 1, "close_beyond_support"), config)
    failed = _advance(confirmed, family, _observation(family, config, 2, "failed_support"), config)
    new = _advance(failed, family, _observation(family, config, 3, "approaching"), config)
    assert new.event_id != failed.event_id
    assert new.state is InteractionEventState.APPROACHING


def test_dormant_event_freezes_and_snapshot_contract_rejects_orphans() -> None:
    config = tracker_config()
    family = interaction_family(config, timestamp())
    active = _advance(None, family, _observation(family, config, 0, "approaching"), config)
    dormant_family = replace(family, lifecycle_state=FamilyLifecycleState.DORMANT)
    frozen = _advance(active, dormant_family, _observation(dormant_family, config, 1, "in_zone_support"), config)
    assert frozen == active

    with pytest.raises(ContractValidationError, match="pending role reversal"):
        replace(active, pending_role_reversal=True)


def test_tracker_persists_event_identity_and_event_state_changes_snapshot_identity() -> None:
    config = tracker_config(events={"pressure_min_bars": 2})
    first_time = timestamp()
    second_time = timestamp(1)
    provider = SequenceProvider(
        (
            valid_result(candidate(config, first_time, candidate_id="first")),
            valid_result(candidate(config, second_time, candidate_id="second")),
        )
    )
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=provider,
        config=config,
    )
    first = tracker.update(tracker_ohlcv(first_time))
    second = tracker.update(tracker_ohlcv(second_time))

    assert len(first.snapshot.interaction_events) == 1
    assert len(second.snapshot.interaction_events) == 1
    assert first.snapshot.interaction_events[0].event_id == second.snapshot.interaction_events[0].event_id
    assert first.snapshot.snapshot_id != second.snapshot.snapshot_id
    assert second.features["trendline_family_event_count"] == 1


def test_snapshot_rejects_duplicate_or_orphan_events_and_invalid_event_evidence() -> None:
    config = tracker_config()
    observed = timestamp()
    output = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(candidate(config, observed)),)),
        config=config,
    ).update(tracker_ohlcv(observed))
    event = output.snapshot.interaction_events[0]

    with pytest.raises(ContractValidationError, match="event IDs must be unique"):
        replace(output.snapshot, interaction_events=(event, event))
    with pytest.raises(ContractValidationError, match="published family"):
        replace(output.snapshot, interaction_events=(replace(event, family_id="orphan"),))
    with pytest.raises(ContractValidationError, match="positive"):
        replace(event, age_bars=0)

    legacy_payload = legacy_pre_phase_g_payload(output.snapshot)
    legacy_payload.pop("interaction_events")
    legacy_payload.pop("interaction_event_transitions")
    assert TrendlineFamilySnapshot.from_dict(legacy_payload).interaction_events == ()


def test_tracker_applies_scheduled_role_reversal_before_matching_without_new_lineage() -> None:
    config = tracker_config()
    times = tuple(timestamp(index) for index in range(5))
    provider = SequenceProvider(
        tuple(
            valid_result(
                candidate(
                    config,
                    observed,
                    candidate_id=f"candidate-{index}",
                    role=(
                        FamilyRole.RESISTANCE
                        if index == len(times) - 1
                        else FamilyRole.SUPPORT
                    ),
                    reference_price=100.2 if index == len(times) - 1 else 100.0,
                )
            )
            for index, observed in enumerate(times)
        )
    )
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=provider,
        config=config,
    )
    candles = (
        (99.4, 100.0, 98.8, 99.0),
        (99.4, 100.0, 98.8, 99.0),
        (99.6, 100.2, 99.4, 99.9),
        (99.4, 100.0, 98.8, 99.0),
        (100.0, 100.2, 99.8, 100.0),
    )
    outputs = []
    for observed, candle_values in zip(times, candles, strict=True):
        frame = tracker_ohlcv(observed)
        frame.iloc[-1] = candle_values
        outputs.append(tracker.update(frame))

    final = outputs[-1].snapshot
    assert len(final.active_families) == 1
    reversed_family = next(
        family for family in final.active_families if family.family_id == outputs[0].snapshot.active_families[0].family_id
    )
    assert reversed_family.current_role is FamilyRole.RESISTANCE
    before_reversal = next(
        family for family in outputs[-2].snapshot.active_families if family.family_id == reversed_family.family_id
    )
    assert reversed_family.members[0].member_id == before_reversal.members[0].member_id
    assert reversed_family.representative == before_reversal.representative
    reversal_transition = next(
        transition
        for transition in final.transitions
        if transition.transition_type.value == "ROLE_REVERSED"
    )
    assert reversal_transition.matched_candidate_ids == ("candidate-3",)
    assert reversal_transition.source_group_candidate_ids == ("candidate-4",)
    reversed_event = next(event for event in final.interaction_events if event.family_id == reversed_family.family_id)
    assert reversed_event.state is InteractionEventState.ROLE_REVERSED
    with pytest.raises(ContractValidationError, match="dormant family cannot retain"):
        replace(
            final,
            active_families=(),
                dormant_families=(
                    replace(reversed_family, lifecycle_state=FamilyLifecycleState.DORMANT),
                ),
                diagnostics={**final.diagnostics, "rail_grouping_enabled": False},
                source_group_audits=(),
        )


def test_tracker_preserves_resistance_geometry_on_matchable_support_reversal() -> None:
    config = tracker_config()
    times = tuple(timestamp(index) for index in range(5))
    provider = SequenceProvider(
        tuple(
            valid_result(
                candidate(
                    config,
                    observed,
                    candidate_id=f"resistance-candidate-{index}",
                    role=(FamilyRole.SUPPORT if index == len(times) - 1 else FamilyRole.RESISTANCE),
                    reference_price=99.8 if index == len(times) - 1 else 100.0,
                )
            )
            for index, observed in enumerate(times)
        )
    )
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=provider,
        config=config,
    )
    candles = (
        (100.6, 101.2, 100.0, 100.9),
        (100.6, 101.2, 100.0, 100.9),
        (100.4, 100.6, 99.8, 100.1),
        (100.6, 101.2, 100.0, 100.9),
        (100.0, 100.2, 99.8, 100.0),
    )
    outputs = []
    for observed, candle_values in zip(times, candles, strict=True):
        frame = tracker_ohlcv(observed)
        frame.iloc[-1] = candle_values
        outputs.append(tracker.update(frame))

    original = outputs[0].snapshot.active_families[0]
    final = outputs[-1].snapshot
    reversed_family = next(family for family in final.active_families if family.family_id == original.family_id)
    before_reversal = next(
        family for family in outputs[-2].snapshot.active_families if family.family_id == original.family_id
    )
    assert reversed_family.current_role is FamilyRole.SUPPORT
    assert reversed_family.representative == before_reversal.representative
    assert reversed_family.members[0].anchors == before_reversal.members[0].anchors
    assert any(
        transition.source_group_candidate_ids == ("resistance-candidate-4",)
        for transition in final.transitions
    )
    with pytest.raises(ContractValidationError, match="dormant family cannot retain"):
        replace(
            final,
            active_families=(),
                dormant_families=(
                    replace(reversed_family, lifecycle_state=FamilyLifecycleState.DORMANT),
                ),
                diagnostics={**final.diagnostics, "rail_grouping_enabled": False},
                source_group_audits=(),
        )


def test_tracker_defers_pending_reversal_through_dormancy_and_reactivation() -> None:
    config = tracker_config(
        lifecycle={
            "active_grace_bars": 0,
            "dormant_after_bars": 1,
            "expire_after_bars": 3,
            "confidence_decay_per_unmatched_bar": 0.10,
            "reactivation_min_score": 0.70,
            "max_active_families_per_role": 2,
        }
    )
    times = tuple(timestamp(index) for index in range(7))
    provider = SequenceProvider(
        (
            *(valid_result(candidate(config, observed, candidate_id=f"support-{index}")) for index, observed in enumerate(times[:4])),
            abstention(),
            valid_result(candidate(config, times[5], candidate_id="support-reactivated")),
            valid_result(
                candidate(
                    config,
                    times[6],
                    candidate_id="resistance-reversal",
                    role=FamilyRole.RESISTANCE,
                    reference_price=100.2,
                )
            ),
        )
    )
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=provider,
        config=config,
    )
    candles = (
        (99.4, 100.0, 98.8, 99.0),
        (99.4, 100.0, 98.8, 99.0),
        (99.6, 100.2, 99.4, 99.9),
        (99.4, 100.0, 98.8, 99.0),
        (100.0, 100.2, 99.8, 100.0),
        (100.0, 100.2, 99.8, 100.0),
        (100.0, 100.2, 99.8, 100.0),
    )
    outputs = []
    for observed, candle_values in zip(times, candles, strict=True):
        frame = tracker_ohlcv(observed)
        frame.iloc[-1] = candle_values
        outputs.append(tracker.update(frame))

    dormant = outputs[4].snapshot
    assert dormant.dormant_families[0].current_role is FamilyRole.SUPPORT
    assert dormant.interaction_events[0].state is InteractionEventState.RETEST_SUCCESS
    assert dormant.interaction_events[0].pending_role_reversal is True
    assert dormant.interaction_event_transitions == ()

    reactivated = outputs[5].snapshot
    assert reactivated.active_families[0].current_role is FamilyRole.SUPPORT
    assert reactivated.interaction_events[0].state is InteractionEventState.RETEST_SUCCESS

    resumed = outputs[6].snapshot
    assert resumed.active_families[0].current_role is FamilyRole.RESISTANCE
    assert resumed.interaction_events[0].state is InteractionEventState.ROLE_REVERSED
    dormant_event = dormant.interaction_events[0]
    forged_frozen = replace(
        resumed.interaction_event_transitions[0],
        event_id=dormant_event.event_id,
        family_id=dormant_event.family_id,
        timestamp=dormant.timestamp,
        trigger_observation_id=dormant_event.last_observation_id,
    )
    with pytest.raises(ContractValidationError, match="frozen interaction event"):
        replace(dormant, interaction_event_transitions=(forged_frozen,))
