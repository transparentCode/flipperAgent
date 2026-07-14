from __future__ import annotations

from libs.models.trendline_family.contracts import InteractionObservationState
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository, serialize_snapshot
from libs.models.trendline_family.tracker import TrendlineFamilyTracker

from .tracker_support import SequenceProvider, candidate, timestamp, tracker_config, tracker_ohlcv, valid_result


def _interaction_replay(*, future_rows: bool) -> tuple[str, ...]:
    config = tracker_config()
    times = (timestamp(), timestamp(1))
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider(
            tuple(valid_result(candidate(config, current, candidate_id=f"candidate-{index}")) for index, current in enumerate(times))
        ),
        config=config,
    )
    full_frame = tracker_ohlcv(timestamp(4), periods=29)
    snapshots = []
    for current in times:
        frame = full_frame if future_rows else full_frame.loc[:current]
        snapshots.append(serialize_snapshot(tracker.update(frame, observed_at=current, tick_size=0.25).snapshot))
    return tuple(snapshots)


def test_interaction_observations_and_snapshots_are_byte_identical_on_replay() -> None:
    assert _interaction_replay(future_rows=False) == _interaction_replay(future_rows=False)


def test_future_rows_do_not_alter_interaction_observation_at_observed_timestamp() -> None:
    assert _interaction_replay(future_rows=False) == _interaction_replay(future_rows=True)


def test_content_addressed_snapshot_id_changes_with_interaction_evidence() -> None:
    config = tracker_config()
    observed = timestamp()
    provider_result = valid_result(candidate(config, observed, candidate_id="same-candidate"))
    in_zone_frame = tracker_ohlcv(observed)
    in_zone_frame.loc[in_zone_frame.index[-1], ["open", "high", "low", "close"]] = (100.8, 101.0, 100.2, 100.8)
    close_beyond_frame = tracker_ohlcv(observed)
    close_beyond_frame.loc[close_beyond_frame.index[-1], ["open", "high", "low", "close"]] = (100.0, 100.0, 98.5, 99.0)
    in_zone = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((provider_result,)),
        config=config,
    ).update(in_zone_frame)
    close_beyond = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((provider_result,)),
        config=config,
    ).update(close_beyond_frame)

    assert in_zone.snapshot.observations[0].state is InteractionObservationState.IN_ZONE
    assert close_beyond.snapshot.observations[0].state is InteractionObservationState.CLOSE_BEYOND
    assert in_zone.snapshot.snapshot_id != close_beyond.snapshot.snapshot_id
