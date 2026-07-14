from __future__ import annotations

import pandas as pd
import pytest

from libs.models.trendline_family.contracts import FamilyLifecycleState, FamilyRole, InteractionObservationState
from libs.models.trendline_family.provider import CandidateGenerationStatus
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository, serialize_snapshot
from libs.models.trendline_family.tracker import TrendlineFamilyTracker, TrendlineFamilyUpdateError

from .tracker_support import SequenceProvider, abstention, candidate, timestamp, tracker_config, tracker_ohlcv, valid_result


def _frame(observed_at, candle: tuple[float, float, float, float]) -> pd.DataFrame:
    frame = tracker_ohlcv(observed_at)
    frame.loc[frame.index[-1], ["open", "high", "low", "close"]] = candle
    return frame


def test_body_and_close_breaches_increment_breach_count_once_without_touch_inflation() -> None:
    config = tracker_config()
    first_time = timestamp()
    second_time = timestamp(1)
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider(
            (
                valid_result(candidate(config, first_time, candidate_id="first")),
                valid_result(candidate(config, second_time, candidate_id="second")),
            )
        ),
        config=config,
    )
    body = tracker.update(_frame(first_time, (99.0, 100.0, 98.5, 100.0)))
    close = tracker.update(_frame(second_time, (100.0, 100.0, 98.5, 99.0)))

    assert body.snapshot.observations[0].state is InteractionObservationState.BODY_BREACH
    assert body.snapshot.active_families[0].breach_count == 1
    assert close.snapshot.observations[0].state is InteractionObservationState.CLOSE_BEYOND
    assert close.snapshot.active_families[0].breach_count == 2
    assert close.snapshot.active_families[0].touch_count == 2
    assert close.snapshot.active_families[0].effective_touch_count == 2


def test_wick_only_breach_does_not_increment_breach_count() -> None:
    config = tracker_config()
    observed = timestamp()
    output = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(candidate(config, observed)),)),
        config=config,
    ).update(_frame(observed, (100.0, 100.0, 99.0, 100.0)))

    assert output.snapshot.observations[0].state is InteractionObservationState.WICK_BREACH
    assert output.snapshot.active_families[0].breach_count == 0


def test_contact_states_reset_touch_age_while_far_and_approaching_increment_it() -> None:
    config = tracker_config(interaction={"approaching_distance_atr": 0.30})
    times = tuple(timestamp(offset) for offset in range(4))
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider(tuple(valid_result(candidate(config, current, candidate_id=f"candidate-{index}")) for index, current in enumerate(times))),
        config=config,
    )
    outputs = (
        tracker.update(_frame(times[0], (100.8, 101.0, 100.2, 100.8))),
        tracker.update(_frame(times[1], (103.0, 104.0, 102.0, 103.0))),
        tracker.update(_frame(times[2], (100.8, 101.0, 100.7, 100.8))),
        tracker.update(_frame(times[3], (100.8, 101.0, 100.2, 100.8))),
    )

    assert outputs[0].snapshot.observations[0].state is InteractionObservationState.IN_ZONE
    assert outputs[0].snapshot.active_families[0].bars_since_touch == 0
    assert outputs[1].snapshot.observations[0].state is InteractionObservationState.FAR
    assert outputs[1].snapshot.active_families[0].bars_since_touch == 1
    assert outputs[2].snapshot.observations[0].state is InteractionObservationState.APPROACHING
    assert outputs[2].snapshot.active_families[0].bars_since_touch == 2
    assert outputs[3].snapshot.observations[0].state is InteractionObservationState.IN_ZONE
    assert outputs[3].snapshot.active_families[0].bars_since_touch == 0


def test_dormant_families_receive_observations_without_reactivation_and_expired_families_do_not() -> None:
    config = tracker_config()
    times = tuple(timestamp(offset) for offset in range(6))
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(candidate(config, times[0])),) + tuple(abstention() for _ in times[1:])),
        config=config,
    )
    outputs = [tracker.update(_frame(current, (100.8, 101.0, 100.2, 100.8))) for current in times]

    dormant = outputs[3].snapshot
    expired = outputs[5].snapshot
    assert dormant.dormant_families[0].lifecycle_state is FamilyLifecycleState.DORMANT
    assert len(dormant.observations) == 1
    assert dormant.observations[0].family_id == dormant.dormant_families[0].family_id
    assert expired.observations == ()
    assert not expired.active_families
    assert not expired.dormant_families


def test_interaction_atr_failure_does_not_persist_partial_snapshot() -> None:
    config = tracker_config()
    first_time = timestamp()
    second_time = timestamp(1)
    repository = InMemoryTrendlineFamilyRepository()
    tracker = TrendlineFamilyTracker(
        repository=repository,
        provider=SequenceProvider(
            (
                valid_result(candidate(config, first_time)),
                abstention(CandidateGenerationStatus.NO_VALID_FITTED_PATHS),
            )
        ),
        config=config,
    )
    tracker.update(_frame(first_time, (100.8, 101.0, 100.2, 100.8)))
    before = repository.latest_snapshot(config.asset, config.timeframe)
    assert before is not None
    one_bar = pd.DataFrame(
        {"open": [100.0], "high": [101.0], "low": [99.0], "close": [100.0]},
        index=pd.DatetimeIndex([second_time]),
    )

    with pytest.raises(TrendlineFamilyUpdateError, match="interaction ATR"):
        tracker.update(one_bar)

    after = repository.latest_snapshot(config.asset, config.timeframe)
    assert after is not None
    assert serialize_snapshot(after) == serialize_snapshot(before)


def test_output_features_are_derived_from_typed_nearest_observations() -> None:
    config = tracker_config()
    observed = timestamp()
    support = candidate(config, observed, candidate_id="support", role=FamilyRole.SUPPORT, reference_price=99.0)
    resistance = candidate(config, observed, candidate_id="resistance", role=FamilyRole.RESISTANCE, reference_price=101.0)
    output = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(support, resistance),)),
        config=config,
    ).update(_frame(observed, (100.0, 101.0, 99.0, 100.0)), tick_size=0.25)
    observations = {observation.family_id: observation for observation in output.snapshot.observations}

    support_observation = observations[output.nearest_support_family_id]
    resistance_observation = observations[output.nearest_resistance_family_id]
    assert output.features["distance_to_support_line_atr"] == support_observation.distance_to_line_atr
    assert output.features["distance_to_resistance_line_atr"] == resistance_observation.distance_to_line_atr
    assert output.features["support_interaction_state"] == support_observation.state.value
    assert output.features["resistance_interaction_state"] == resistance_observation.state.value
    assert support_observation.tick_size == 0.25


def test_interaction_width_never_changes_family_member_identity_or_exact_geometry() -> None:
    observed = timestamp()
    narrow = tracker_config(interaction={"tolerance_atr": 0.10, "approaching_distance_atr": 0.50})
    wide = tracker_config(interaction={"tolerance_atr": 0.50, "approaching_distance_atr": 0.50})
    frame = _frame(observed, (100.8, 101.0, 100.2, 100.8))
    narrow_output = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(candidate(narrow, observed, candidate_id="same")),)),
        config=narrow,
    ).update(frame)
    wide_output = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(candidate(wide, observed, candidate_id="same")),)),
        config=wide,
    ).update(frame)

    narrow_family = narrow_output.snapshot.active_families[0]
    wide_family = wide_output.snapshot.active_families[0]
    assert narrow_family.family_id == wide_family.family_id
    assert narrow_family.members[0].member_id == wide_family.members[0].member_id
    assert narrow_family.representative == wide_family.representative
    assert narrow_output.snapshot.observations[0].zone != wide_output.snapshot.observations[0].zone
