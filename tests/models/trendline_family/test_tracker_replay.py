from __future__ import annotations

from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository, serialize_snapshot
from libs.models.trendline_family.tracker import TrendlineFamilyTracker

from .tracker_support import SequenceProvider, abstention, candidate, timestamp, tracker_config, tracker_ohlcv, valid_result


def _run_replay(*, future_rows: bool) -> tuple[str, ...]:
    config = tracker_config()
    times = (timestamp(), timestamp(1), timestamp(2))
    results = (
        valid_result(candidate(config, times[0], candidate_id="first", quality=0.70)),
        valid_result(candidate(config, times[1], candidate_id="second", reference_price=100.2, quality=0.80)),
        abstention(),
    )
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider(results),
        config=config,
    )
    full_frame = tracker_ohlcv(timestamp(4), periods=29)
    snapshots = []
    for current in times:
        frame = full_frame if future_rows else full_frame.loc[:current]
        snapshots.append(serialize_snapshot(tracker.update(frame, observed_at=current).snapshot))
    return tuple(snapshots)


def test_repeated_identical_replay_is_byte_identical() -> None:
    assert _run_replay(future_rows=False) == _run_replay(future_rows=False)


def test_future_rows_do_not_alter_update_at_observed_timestamp() -> None:
    assert _run_replay(future_rows=False) == _run_replay(future_rows=True)


def _continuation_ids(*, reference_price: float, quality: float) -> tuple[str, str]:
    config = tracker_config()
    first_time = timestamp()
    second_time = timestamp(1)
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider(
            (
                valid_result(candidate(config, first_time, candidate_id="first", quality=0.70)),
                valid_result(
                    candidate(
                        config,
                        second_time,
                        candidate_id="continuation",
                        reference_price=reference_price,
                        quality=quality,
                    )
                ),
            )
        ),
        config=config,
    )
    tracker.update(tracker_ohlcv(first_time))
    output = tracker.update(tracker_ohlcv(second_time))
    return output.snapshot.snapshot_id, output.snapshot.transitions[0].transition_id


def test_content_addressed_ids_change_with_result_geometry_confidence_and_association() -> None:
    first = _continuation_ids(reference_price=100.1, quality=0.80)
    second = _continuation_ids(reference_price=100.2, quality=0.90)

    assert first[0] != second[0]
    assert first[1] != second[1]


def test_empty_snapshot_id_includes_diagnostic_content() -> None:
    config = tracker_config()
    observed = timestamp()
    quiet = tracker_ohlcv(observed)
    volatile = quiet.copy()
    volatile.loc[volatile.index[-1], ["high", "low"]] = (110.0, 90.0)

    quiet_output = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((abstention(),)),
        config=config,
    ).update(quiet)
    volatile_output = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((abstention(),)),
        config=config,
    ).update(volatile)

    assert quiet_output.snapshot.diagnostics["normalization_atr"] != volatile_output.snapshot.diagnostics[
        "normalization_atr"
    ]
    assert quiet_output.snapshot.snapshot_id != volatile_output.snapshot.snapshot_id
