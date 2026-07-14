"""Phase-G deterministic multi-rail family, corridor, and identity coverage."""

from __future__ import annotations

from dataclasses import replace

import pytest

from libs.models.trendline_family.config import RailsConfig
from libs.models.trendline_family.contracts import (
    ContractValidationError,
    FamilyRole,
    InteractionEventState,
    TrendlineFamilySnapshot,
)
from libs.models.trendline_family.features import build_interaction_features
from libs.models.trendline_family.matching import calculate_normalization_atr
from libs.models.trendline_family.rails import group_rail_candidates
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository, serialize_snapshot
from libs.models.trendline_family.tracker import TrendlineFamilyTracker

from .tracker_support import (
    SequenceProvider,
    abstention,
    candidate,
    timestamp,
    tracker_config,
    tracker_ohlcv,
    valid_result,
)


def _rail_config(**overrides):
    return tracker_config(
        rails={
            "minimum_spacing_atr": 0.01,
            "max_adjacent_gap_atr": 0.50,
            "max_corridor_width_atr": 1.00,
            **overrides,
        }
    )


def _multi_support(config, observed_at, *, suffix: str, left: float = 100.0, right: float = 100.4):
    return (
        candidate(
            config,
            observed_at,
            candidate_id=f"left-{suffix}",
            reference_price=left,
            anchor_prefix="left",
        ),
        candidate(
            config,
            observed_at,
            candidate_id=f"right-{suffix}",
            reference_price=right,
            anchor_prefix="right",
        ),
    )


def test_complete_linkage_grouping_is_order_independent_and_rejects_chains() -> None:
    config = _rail_config(max_adjacent_gap_atr=0.15, max_corridor_width_atr=0.15)
    observed = timestamp()
    frame = tracker_ohlcv(observed)
    atr = calculate_normalization_atr(frame, window=config.matching.normalization_atr_window)
    candidates = (
        candidate(config, observed, candidate_id="a", reference_price=100.0, anchor_prefix="a"),
        candidate(config, observed, candidate_id="b", reference_price=100.2, anchor_prefix="b"),
        candidate(config, observed, candidate_id="c", reference_price=100.4, anchor_prefix="c"),
    )

    forward = group_rail_candidates(candidates, timestamp=observed, atr=atr, config=config)
    reversed_result = group_rail_candidates(
        tuple(reversed(candidates)), timestamp=observed, atr=atr, config=config
    )

    assert tuple(group.candidate_ids for group in forward.groups) == (("a", "b"), ("c",))
    assert forward == reversed_result
    assert "complete_linkage_rejected" in forward.rejected_pair_reason_codes
    assert "corridor_width_exceeds_maximum" in forward.rejected_pair_reason_codes


def test_grouping_keeps_roles_and_incompatible_slopes_separate() -> None:
    config = _rail_config(max_group_slope_delta_atr_per_hour=0.02)
    observed = timestamp()
    atr = calculate_normalization_atr(
        tracker_ohlcv(observed), window=config.matching.normalization_atr_window
    )
    candidates = (
        candidate(config, observed, candidate_id="support", anchor_prefix="support"),
        candidate(
            config,
            observed,
            candidate_id="resistance",
            role=FamilyRole.RESISTANCE,
            anchor_prefix="resistance",
        ),
        candidate(
            config,
            observed,
            candidate_id="steep",
            reference_price=100.2,
            slope_per_hour=0.10,
            anchor_prefix="steep",
        ),
    )

    result = group_rail_candidates(candidates, timestamp=observed, atr=atr, config=config)

    assert all(len(group.candidate_ids) == 1 for group in result.groups)


def test_crossing_rails_are_split_without_swapping_exact_identity() -> None:
    config = _rail_config(max_group_slope_delta_atr_per_hour=0.20)
    observed = timestamp()
    atr = calculate_normalization_atr(
        tracker_ohlcv(observed), window=config.matching.normalization_atr_window
    )
    rising = candidate(
        config,
        observed,
        candidate_id="rising",
        reference_price=100.0,
        slope_per_hour=0.10,
        anchor_prefix="rising",
    )
    falling = candidate(
        config,
        observed,
        candidate_id="falling",
        reference_price=100.2,
        slope_per_hour=-0.10,
        anchor_prefix="falling",
    )

    result = group_rail_candidates(
        (rising, falling), timestamp=observed, atr=atr, config=config
    )

    assert {group.candidate_ids for group in result.groups} == {("falling",), ("rising",)}
    assert "complete_linkage_rejected" in result.rejected_pair_reason_codes


@pytest.mark.parametrize(
    ("rail_override", "left_slope", "right_slope"),
    (
        ({"max_group_slope_delta_atr_per_hour": 0.01}, 0.0, 0.10),
        ({"max_adjacent_gap_atr": 0.15, "max_corridor_width_atr": 1.00}, 0.0, 0.0),
        ({"max_adjacent_gap_atr": 0.50, "max_corridor_width_atr": 0.15}, 0.0, 0.0),
        ({"minimum_spacing_atr": 0.25}, 0.0, 0.0),
    ),
)
def test_each_rail_grouping_parameter_changes_only_grouping(
    rail_override,
    left_slope,
    right_slope,
) -> None:
    baseline = _rail_config(max_group_slope_delta_atr_per_hour=0.08)
    adjusted_rails = {"max_group_slope_delta_atr_per_hour": 0.08, **rail_override}
    adjusted = _rail_config(**adjusted_rails)
    observed = timestamp()
    baseline_atr = calculate_normalization_atr(
        tracker_ohlcv(observed), window=baseline.matching.normalization_atr_window
    )
    adjusted_atr = calculate_normalization_atr(
        tracker_ohlcv(observed), window=adjusted.matching.normalization_atr_window
    )
    baseline_candidates = (
        candidate(
            baseline,
            observed,
            candidate_id="left",
            slope_per_hour=left_slope,
            anchor_prefix="left",
        ),
        candidate(
            baseline,
            observed,
            candidate_id="right",
            reference_price=100.4,
            slope_per_hour=right_slope,
            anchor_prefix="right",
        ),
    )
    adjusted_candidates = (
        candidate(
            adjusted,
            observed,
            candidate_id="left",
            slope_per_hour=left_slope,
            anchor_prefix="left",
        ),
        candidate(
            adjusted,
            observed,
            candidate_id="right",
            reference_price=100.4,
            slope_per_hour=right_slope,
            anchor_prefix="right",
        ),
    )

    baseline_result = group_rail_candidates(
        baseline_candidates, timestamp=observed, atr=baseline_atr, config=baseline
    )
    adjusted_result = group_rail_candidates(
        adjusted_candidates, timestamp=observed, atr=adjusted_atr, config=adjusted
    )

    assert len(baseline_result.groups) == 1
    assert len(adjusted_result.groups) == 2
    assert baseline.interaction == adjusted.interaction
    assert baseline.events == adjusted.events
    assert tuple(item.geometry for item in baseline_candidates) == tuple(
        item.geometry for item in adjusted_candidates
    )


def test_multi_rail_corridor_is_derived_and_interactions_stay_on_exact_representative() -> None:
    config = _rail_config()
    observed = timestamp()
    output = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(*_multi_support(config, observed, suffix="first")),)),
        config=config,
    ).update(tracker_ohlcv(observed))

    family = output.snapshot.active_families[0]
    corridor = output.snapshot.corridors[0]
    observation = output.snapshot.observations[0]
    representative = next(
        member for member in family.members if member.member_id == family.representative_member_id
    )

    assert len(family.members) == 2
    assert corridor.rail_count == 2
    assert corridor.family_id == family.family_id
    assert corridor.center_price == pytest.approx(representative.geometry.value_at(observed))
    assert corridor.width_absolute > 0.0
    assert observation.exact_line_price == pytest.approx(representative.geometry.value_at(observed))
    assert output.features["support_rail_count"] == 2
    assert output.features["support_corridor_width_atr"] == corridor.width_atr
    assert output.features["support_current_corridor_position"] is not None


def test_singleton_growth_and_contraction_preserve_family_and_member_continuity() -> None:
    config = _rail_config()
    first_time, second_time, third_time = timestamp(), timestamp(1), timestamp(2)
    initial = candidate(config, first_time, candidate_id="seed", anchor_prefix="seed")
    continued, added = _multi_support(
        config,
        second_time,
        suffix="grow",
        left=100.1,
        right=100.5,
    )
    continued = replace(continued, candidate_id="seed-next", anchors=initial.anchors)
    final = candidate(
        config,
        third_time,
        candidate_id="seed-final",
        reference_price=100.2,
        anchor_prefix="seed",
    )
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider(
            (
                valid_result(initial),
                valid_result(continued, added),
                valid_result(final),
            )
        ),
        config=config,
    )

    first = tracker.update(tracker_ohlcv(first_time)).snapshot
    grown = tracker.update(tracker_ohlcv(second_time)).snapshot
    contracted = tracker.update(tracker_ohlcv(third_time)).snapshot
    seed_member_id = first.active_families[0].members[0].member_id

    assert grown.active_families[0].family_id == first.active_families[0].family_id
    assert len(grown.active_families[0].members) == 2
    assert seed_member_id in {member.member_id for member in grown.active_families[0].members}
    assert grown.transitions[0].added_member_ids
    assert contracted.active_families[0].family_id == first.active_families[0].family_id
    assert tuple(member.member_id for member in contracted.active_families[0].members) == (seed_member_id,)
    assert contracted.transitions[0].removed_member_ids


def test_representative_change_starts_a_new_event_episode_without_synthetic_geometry() -> None:
    config = _rail_config()
    first_time, second_time = timestamp(), timestamp(1)
    left, right = _multi_support(config, first_time, suffix="first")
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(left, right),)),
        config=config,
    )

    first = tracker.update(tracker_ohlcv(first_time)).snapshot
    first_family = first.active_families[0]
    retained = next(
        member
        for member in first_family.members
        if member.member_id != first_family.representative_member_id
    )
    right_only = replace(
        candidate(
            config,
            second_time,
            candidate_id="retained-next",
            reference_price=retained.geometry.value_at(second_time),
            anchor_prefix="retained",
        ),
        anchors=retained.anchors,
    )
    tracker.provider = SequenceProvider((valid_result(right_only),))
    second = tracker.update(tracker_ohlcv(second_time)).snapshot
    transition = second.transitions[0]
    family = second.active_families[0]

    assert transition.representative_changed is True
    assert second.interaction_events[0].previous_state is None
    assert family.representative == family.members[0].geometry
    assert family.representative_member_id != first.active_families[0].representative_member_id


@pytest.mark.parametrize(
    ("initial_role", "reversed_role", "close_beyond", "in_zone"),
    (
        (FamilyRole.SUPPORT, FamilyRole.RESISTANCE, (99.4, 100.0, 98.8, 99.0), (99.6, 100.2, 99.4, 99.9)),
        (FamilyRole.RESISTANCE, FamilyRole.SUPPORT, (100.6, 101.2, 100.0, 100.9), (100.5, 100.6, 99.8, 100.5)),
    ),
)
def test_multi_rail_role_reversal_preserves_every_exact_member(
    initial_role,
    reversed_role,
    close_beyond,
    in_zone,
) -> None:
    config = _rail_config()
    times = tuple(timestamp(index) for index in range(5))

    def rails(observed, suffix, role):
        return (
            candidate(
                config,
                observed,
                candidate_id=f"left-{suffix}",
                role=role,
                reference_price=100.0,
                anchor_prefix="left",
            ),
            candidate(
                config,
                observed,
                candidate_id=f"right-{suffix}",
                role=role,
                reference_price=100.4,
                anchor_prefix="right",
            ),
        )

    provider = SequenceProvider(
        (
            *(valid_result(*rails(observed, str(index), initial_role)) for index, observed in enumerate(times[:4])),
            valid_result(*rails(times[4], "reversed", reversed_role)),
        )
    )
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(), provider=provider, config=config
    )
    candles = (close_beyond, close_beyond, in_zone, close_beyond, in_zone)
    snapshots = []
    for observed, candle in zip(times, candles, strict=True):
        frame = tracker_ohlcv(observed)
        frame.iloc[-1] = candle
        snapshots.append(tracker.update(frame).snapshot)

    before = snapshots[-2].active_families[0]
    reversed_family = snapshots[-1].active_families[0]
    assert reversed_family.family_id == before.family_id
    assert reversed_family.current_role is reversed_role
    assert tuple(member.member_id for member in reversed_family.members) == tuple(
        member.member_id for member in before.members
    )
    assert tuple(member.geometry for member in reversed_family.members) == tuple(
        member.geometry for member in before.members
    )
    assert tuple(member.anchors for member in reversed_family.members) == tuple(
        member.anchors for member in before.members
    )
    assert reversed_family.representative_member_id == before.representative_member_id
    assert snapshots[-1].interaction_events[0].state is InteractionEventState.ROLE_REVERSED
    assert snapshots[-1].corridors[0].rail_count == 2


def test_rail_config_contract_and_snapshot_replay_are_input_sensitive() -> None:
    with pytest.raises(ContractValidationError, match="minimum_spacing"):
        RailsConfig(minimum_spacing_atr=0.75, max_adjacent_gap_atr=0.75)
    config = _rail_config()
    observed = timestamp()
    output = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(*_multi_support(config, observed, suffix="replay")),)),
        config=config,
    ).update(tracker_ohlcv(observed))
    payload = serialize_snapshot(output.snapshot)

    assert output.snapshot.from_dict(output.snapshot.to_dict()).to_dict() == output.snapshot.to_dict()
    assert payload == serialize_snapshot(output.snapshot)
    with pytest.raises(ContractValidationError, match="corridors must cover"):
        replace(output.snapshot, corridors=())

def test_non_representative_member_continuation_retains_family_outside_representative_gate() -> None:
    config = tracker_config(
        matching={"max_distance_atr": 0.10},
        rails={
            "minimum_spacing_atr": 0.01,
            "max_adjacent_gap_atr": 0.50,
            "max_corridor_width_atr": 1.00,
        },
    )
    first_time, second_time = timestamp(), timestamp(1)
    left = candidate(config, first_time, candidate_id="left", reference_price=100.0, anchor_prefix="left")
    middle = candidate(config, first_time, candidate_id="middle", reference_price=100.4, anchor_prefix="middle")
    right = candidate(config, first_time, candidate_id="right", reference_price=100.8, anchor_prefix="right")
    outer_continuation = replace(
        candidate(
            config,
            second_time,
            candidate_id="left-next",
            reference_price=100.0,
            anchor_prefix="left",
        ),
        anchors=left.anchors,
    )
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(left, middle, right), valid_result(outer_continuation))),
        config=config,
    )

    first = tracker.update(tracker_ohlcv(first_time)).snapshot
    second = tracker.update(tracker_ohlcv(second_time)).snapshot

    assert first.active_families[0].representative_member_id != next(
        member.member_id
        for member in first.active_families[0].members
        if member.candidate_id == "left"
    )
    assert len(second.active_families) == 1
    assert second.active_families[0].family_id == first.active_families[0].family_id
    assert second.active_families[0].members[0].candidate_id == "left-next"


def test_dormant_multi_rail_reactivates_from_a_non_representative_member() -> None:
    config = tracker_config(
        matching={"max_distance_atr": 0.10},
        lifecycle={
            "active_grace_bars": 0,
            "dormant_after_bars": 1,
            "expire_after_bars": 3,
            "confidence_decay_per_unmatched_bar": 0.10,
            "reactivation_min_score": 0.70,
        },
        rails={
            "minimum_spacing_atr": 0.01,
            "max_adjacent_gap_atr": 0.50,
            "max_corridor_width_atr": 1.00,
        },
    )
    first_time, dormant_time, reactivate_time = timestamp(), timestamp(1), timestamp(2)
    left = candidate(config, first_time, candidate_id="left", reference_price=100.0, anchor_prefix="left")
    middle = candidate(config, first_time, candidate_id="middle", reference_price=100.4, anchor_prefix="middle")
    right = candidate(config, first_time, candidate_id="right", reference_price=100.8, anchor_prefix="right")
    outer_continuation = replace(
        candidate(
            config,
            reactivate_time,
            candidate_id="left-reactivated",
            reference_price=100.0,
            anchor_prefix="left",
        ),
        anchors=left.anchors,
    )
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider(
            (
                valid_result(left, middle, right),
                abstention(),
                valid_result(outer_continuation),
            )
        ),
        config=config,
    )

    first = tracker.update(tracker_ohlcv(first_time)).snapshot
    dormant = tracker.update(tracker_ohlcv(dormant_time)).snapshot
    reactivated = tracker.update(tracker_ohlcv(reactivate_time)).snapshot

    assert dormant.dormant_families[0].family_id == first.active_families[0].family_id
    assert reactivated.active_families[0].family_id == first.active_families[0].family_id
    assert reactivated.transitions[0].transition_type.value == "REACTIVATE"


def test_reversal_suppresses_all_stale_old_role_rails_in_both_directions() -> None:
    cases = (
        (FamilyRole.SUPPORT, FamilyRole.RESISTANCE, (99.4, 100.0, 98.8, 99.0), (99.6, 100.2, 99.4, 99.9)),
        (FamilyRole.RESISTANCE, FamilyRole.SUPPORT, (100.6, 101.2, 100.0, 100.9), (100.5, 100.6, 99.8, 100.5)),
    )
    for initial_role, reversed_role, close_beyond, in_zone in cases:
        config = _rail_config()
        times = tuple(timestamp(index) for index in range(5))

        def rails(observed, suffix, role):
            return (
                candidate(
                    config,
                    observed,
                    candidate_id=f"left-{suffix}",
                    role=role,
                    reference_price=100.0,
                    anchor_prefix="left",
                ),
                candidate(
                    config,
                    observed,
                    candidate_id=f"right-{suffix}",
                    role=role,
                    reference_price=100.4,
                    anchor_prefix="right",
                ),
            )

        provider = SequenceProvider(
            (
                *(valid_result(*rails(observed, str(index), initial_role)) for index, observed in enumerate(times[:4])),
                valid_result(
                    *rails(times[4], "new-role", reversed_role),
                    *rails(times[4], "stale-old-role", initial_role),
                ),
            )
        )
        tracker = TrendlineFamilyTracker(
            repository=InMemoryTrendlineFamilyRepository(), provider=provider, config=config
        )
        snapshots = []
        for observed, candle in zip(
            times,
            (close_beyond, close_beyond, in_zone, close_beyond, in_zone),
            strict=True,
        ):
            frame = tracker_ohlcv(observed)
            frame.iloc[-1] = candle
            snapshots.append(tracker.update(frame).snapshot)

        final = snapshots[-1]
        assert len(final.active_families) == 1
        assert final.active_families[0].family_id == snapshots[0].active_families[0].family_id
        assert final.active_families[0].current_role is reversed_role
        assert final.interaction_events[0].state is InteractionEventState.ROLE_REVERSED


def test_reversal_births_only_the_independent_residual_rail() -> None:
    config = tracker_config(
        matching={"max_distance_atr": 0.10},
        rails={
            "minimum_spacing_atr": 0.01,
            "max_adjacent_gap_atr": 0.50,
            "max_corridor_width_atr": 1.00,
        },
    )
    times = tuple(timestamp(index) for index in range(5))

    def rails(observed, suffix, role):
        return (
            candidate(
                config,
                observed,
                candidate_id=f"left-{suffix}",
                role=role,
                reference_price=100.0,
                anchor_prefix="left",
            ),
            candidate(
                config,
                observed,
                candidate_id=f"right-{suffix}",
                role=role,
                reference_price=100.4,
                anchor_prefix="right",
            ),
        )

    independent = candidate(
        config,
        times[4],
        candidate_id="independent-old-role",
        role=FamilyRole.SUPPORT,
        reference_price=100.8,
        anchor_prefix="independent",
    )
    provider = SequenceProvider(
        (
            *(valid_result(*rails(observed, str(index), FamilyRole.SUPPORT)) for index, observed in enumerate(times[:4])),
            valid_result(
                *rails(times[4], "new-role", FamilyRole.RESISTANCE),
                *rails(times[4], "stale-old-role", FamilyRole.SUPPORT),
                independent,
            ),
        )
    )
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(), provider=provider, config=config
    )
    snapshots = []
    for observed, candle in zip(
        times,
        ((99.4, 100.0, 98.8, 99.0),) * 2 + ((99.6, 100.2, 99.4, 99.9), (99.4, 100.0, 98.8, 99.0), (99.6, 100.2, 99.4, 99.9)),
        strict=True,
    ):
        frame = tracker_ohlcv(observed)
        frame.iloc[-1] = candle
        snapshots.append(tracker.update(frame).snapshot)

    final = snapshots[-1]
    original_family_id = snapshots[0].active_families[0].family_id
    reversed_family = next(family for family in final.active_families if family.family_id == original_family_id)
    residual_family = next(family for family in final.active_families if family.family_id != original_family_id)
    assert reversed_family.current_role is FamilyRole.RESISTANCE
    assert residual_family.current_role is FamilyRole.SUPPORT
    assert tuple(member.candidate_id for member in residual_family.members) == (
        "independent-old-role",
    )


def test_partial_new_role_reversal_preserves_representative_and_event_episode() -> None:
    config = _rail_config()
    times = tuple(timestamp(index) for index in range(5))

    def rails(observed, suffix, role):
        return _multi_support(config, observed, suffix=suffix) if role is FamilyRole.SUPPORT else tuple(
            replace(rail, role=FamilyRole.RESISTANCE)
            for rail in _multi_support(config, observed, suffix=suffix)
        )

    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider(
            tuple(valid_result(*rails(observed, str(index), FamilyRole.SUPPORT)) for index, observed in enumerate(times[:4]))
        ),
        config=config,
    )
    snapshots = []
    for observed, candle in zip(
        times[:4],
        ((99.4, 100.0, 98.8, 99.0),) * 2 + ((99.6, 100.2, 99.4, 99.9), (99.4, 100.0, 98.8, 99.0)),
        strict=True,
    ):
        frame = tracker_ohlcv(observed)
        frame.iloc[-1] = candle
        snapshots.append(tracker.update(frame).snapshot)
    before = snapshots[-1]
    previous_family = before.active_families[0]
    retained = next(
        member
        for member in previous_family.members
        if member.member_id != previous_family.representative_member_id
    )
    partial = replace(
        candidate(
            config,
            times[4],
            candidate_id="partial-new-role",
            role=FamilyRole.RESISTANCE,
            reference_price=retained.geometry.value_at(times[4]),
            anchor_prefix="retained",
        ),
        anchors=retained.anchors,
    )
    tracker.provider = SequenceProvider((valid_result(partial),))
    frame = tracker_ohlcv(times[4])
    frame.iloc[-1] = (99.6, 100.2, 99.4, 99.9)
    final = tracker.update(frame).snapshot

    family = final.active_families[0]
    transition = final.transitions[0]
    assert family.representative_member_id == previous_family.representative_member_id
    assert tuple(member.member_id for member in family.members) == tuple(
        member.member_id for member in previous_family.members
    )
    assert transition.representative_changed is False
    assert "representative_changed" not in transition.reason_codes
    assert final.interaction_events[0].event_id == before.interaction_events[0].event_id
    assert final.interaction_events[0].state is InteractionEventState.ROLE_REVERSED


def test_phase_g_corridor_and_transition_contracts_bind_persisted_exact_truth() -> None:
    config = _rail_config()
    observed = timestamp()
    output = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(*_multi_support(config, observed, suffix="bound")),)),
        config=config,
    ).update(tracker_ohlcv(observed))
    corridor = output.snapshot.corridors[0]
    transition = output.snapshot.transitions[0]

    with pytest.raises(ContractValidationError, match="lower_price"):
        replace(
            corridor,
            lower_price=corridor.lower_price - 0.1,
            width_absolute=corridor.width_absolute + 0.1,
        )
    with pytest.raises(ContractValidationError, match="center_price"):
        replace(
            corridor,
            center_price=(corridor.lower_price + corridor.upper_price) / 2.0,
        )
    with pytest.raises(ContractValidationError, match="current_rail_count"):
        replace(transition, current_rail_count=99)
    with pytest.raises(ContractValidationError, match="transition_id"):
        replace(output.snapshot, transitions=(replace(transition, transition_id="forged"),))


def test_phase_g_corridor_features_are_reproducible_from_serialized_observation_close() -> None:
    config = _rail_config()
    observed = timestamp()
    output = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(*_multi_support(config, observed, suffix="features")),)),
        config=config,
    ).update(tracker_ohlcv(observed))
    restored = TrendlineFamilySnapshot.from_dict(output.snapshot.to_dict())
    persisted_features = build_interaction_features(
        restored,
        nearest_support_family_id=output.nearest_support_family_id,
        nearest_resistance_family_id=output.nearest_resistance_family_id,
    )
    asserted_features = build_interaction_features(
        restored,
        nearest_support_family_id=output.nearest_support_family_id,
        nearest_resistance_family_id=output.nearest_resistance_family_id,
        current_price=restored.observations[0].close_price,
    )

    phase_g_keys = tuple(key for key in persisted_features if "rail" in key or "corridor" in key)
    assert {key: persisted_features[key] for key in phase_g_keys} == {
        key: asserted_features[key] for key in phase_g_keys
    }
    with pytest.raises(ContractValidationError, match="persisted observation close_price"):
        build_interaction_features(
            restored,
            nearest_support_family_id=output.nearest_support_family_id,
            nearest_resistance_family_id=output.nearest_resistance_family_id,
            current_price=1000.0,
        )
