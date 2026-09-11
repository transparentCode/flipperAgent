"""Contract tests for causal research replay."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd
import pytest

from libs.models.trendlines.config import load_trendlines_config
from libs.models.trendlines.contracts.identity import resolve_source_ref
from libs.models.trendlines.workflows.research import (
    PreparedTrendlineResearchRun,
    TrendlineReplayContractError,
    TrendlineReplayIntegrityError,
    ReplayFutureInvarianceError,
    TrendlineReplayWindow,
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    TrendlineResearchPurpose,
    TrendlineResearchReplaySpec,
    TrendlineResearchSpec,
    prepare_trendline_research,
    run_causal_replay,
    verify_replay_future_invariance,
)


def _prepared(
    *,
    timeframes: tuple[str, ...] = ("1h",),
    count: int = 48,
    extractor: str | None = None,
) -> PreparedTrendlineResearchRun:
    config = load_trendlines_config()
    if extractor is not None:
        config = replace(config, extractor=extractor)
    spec = TrendlineResearchSpec(
        purpose=TrendlineResearchPurpose.SMOKE,
        data=TrendlineResearchDataSpec(
            mode=TrendlineResearchDataMode.SYNTHETIC,
            seed=42,
            start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            bar_counts={timeframe: count for timeframe in timeframes},
        ),
        asset="BTCUSDT",
        timeframes=timeframes,
        primary_timeframe=timeframes[0],
    )
    return asyncio.run(
        prepare_trendline_research(spec, trendlines_config=config)
    )


def _replay(
    prepared: PreparedTrendlineResearchRun,
    *,
    end: int = 25,
    include_signals: bool = False,
    warmup: int = 19,
    record_start: int = 20,
    record_every: int = 1,
):
    return run_causal_replay(
        prepared,
        TrendlineResearchReplaySpec(
            windows={
                timeframe: TrendlineReplayWindow(
                    warmup,
                    record_start,
                    end,
                    record_every,
                )
                for timeframe in prepared.spec.timeframes
            },
            include_signals=include_signals,
        ),
    )


def _injected_prepared(
    frames: dict[str, pd.DataFrame],
    *,
    timeframes: tuple[str, ...],
) -> PreparedTrendlineResearchRun:
    spec = TrendlineResearchSpec(
        purpose=TrendlineResearchPurpose.SMOKE,
        data=TrendlineResearchDataSpec(mode=TrendlineResearchDataMode.INJECTED),
        asset="BTCUSDT",
        timeframes=timeframes,
        primary_timeframe=timeframes[0],
    )
    return asyncio.run(
        prepare_trendline_research(
            spec,
            trendlines_config=load_trendlines_config(),
            loader=frames,
        )
    )


def test_replay_windows_reject_invalid_bounds_and_strides() -> None:
    with pytest.raises(TrendlineReplayContractError):
        TrendlineReplayWindow(True, 1, 2, 1)
    with pytest.raises(TrendlineReplayContractError):
        TrendlineReplayWindow(2, 1, 3, 1)
    with pytest.raises(TrendlineReplayContractError):
        TrendlineReplayWindow(1, 2, 3, 0)
    with pytest.raises(TrendlineReplayContractError):
        TrendlineReplayWindow(1, 2, 3, 1).validate_for(3, timeframe="1h")


def test_replay_windows_cover_prepared_timeframes_exactly() -> None:
    prepared = _prepared(timeframes=("1h", "2h"))
    wrong_order = TrendlineResearchReplaySpec(
        windows={
            "2h": TrendlineReplayWindow(19, 20, 21, 1),
            "1h": TrendlineReplayWindow(19, 20, 21, 1),
        },
        include_signals=False,
    )
    with pytest.raises(TrendlineReplayContractError):
        run_causal_replay(prepared, wrong_order)


def test_warmup_and_intermediate_positions_execute_but_are_not_recorded() -> None:
    replay = _replay(_prepared(), end=24, record_start=21, record_every=2)
    timeframe = replay.timeframes["1h"]
    assert timeframe.executed_positions == (19, 20, 21, 22, 23, 24)
    assert timeframe.warmup_position_count == 2
    assert timeframe.recorded_positions == (21, 23)
    with pytest.raises(TrendlineReplayContractError):
        timeframe.output_at(22)


def test_replay_is_deterministic_across_identical_runs() -> None:
    prepared = _prepared()
    left = _replay(prepared, end=23)
    right = _replay(prepared, end=23)
    assert left.replay_id == right.replay_id
    assert left.to_dict() == right.to_dict()


def test_full_and_truncated_replays_are_future_row_invariant() -> None:
    full_prepared = _prepared()
    full_frame = full_prepared.dataset.frames["1h"]
    truncated_frame = full_frame.iloc[:24].copy()
    truncated_frame.attrs = dict(full_frame.attrs)
    truncated_prepared = _injected_prepared(
        {"1h": truncated_frame},
        timeframes=("1h",),
    )
    full = _replay(full_prepared, end=27)
    truncated = _replay(truncated_prepared, end=23)
    assert full_prepared.dataset.dataset_id != truncated_prepared.dataset.dataset_id
    assert full_prepared.preparation_id != truncated_prepared.preparation_id
    verify_replay_future_invariance(full, truncated, timeframe="1h", position=22)


def test_changed_shared_prefix_fails_with_structured_invariance_details() -> None:
    full_prepared = _prepared()
    full_frame = full_prepared.dataset.frames["1h"]
    changed_frame = full_frame.iloc[:24].copy()
    changed_frame.attrs = dict(full_frame.attrs)
    changed_frame.loc[changed_frame.index[5], "volume"] += 1.0
    changed_prepared = _injected_prepared(
        {"1h": changed_frame},
        timeframes=("1h",),
    )
    full = _replay(full_prepared, end=27)
    changed = _replay(changed_prepared, end=23)
    with pytest.raises(ReplayFutureInvarianceError) as exc_info:
        verify_replay_future_invariance(full, changed, timeframe="1h", position=22)
    assert any(item.field == "prefix_source_id" for item in exc_info.value.mismatches)


def test_prefix_source_identity_matches_independent_prefix_computation() -> None:
    prepared = _prepared()
    replay = _replay(prepared, end=23)
    point = replay.output_at("1h", 22)
    prefix = prepared.dataset.frames["1h"].iloc[:23]
    expected = resolve_source_ref(prefix)
    assert point.prefix_source_ref == expected


def test_point_availability_equals_exact_final_prefix_availability() -> None:
    prepared = _prepared()
    replay = _replay(prepared, end=22)
    point = replay.latest("1h")
    frame = prepared.dataset.frames["1h"]
    assert point.available_at == frame["bar_available_at"].iloc[point.position].to_pydatetime()
    assert point.event_at == frame.index[point.position].to_pydatetime()


def test_preparation_identity_mismatch_is_rejected_by_diagnostics_binding() -> None:
    prepared = _prepared()
    other = _prepared()
    replay = _replay(prepared, end=22)
    from libs.models.trendlines.workflows.research.diagnostics import inspect_replay_pivots

    with pytest.raises(TrendlineReplayContractError):
        inspect_replay_pivots(other, replay, timeframe="1h", position=20)


def test_signal_replay_selects_only_knowledge_time_available_history() -> None:
    replay = _replay(_prepared(), end=23, include_signals=True)
    point = replay.output_at("1h", 22)
    metadata = point.output.metadata
    assert metadata["signal_query_known_at"] == point.available_at.isoformat()
    assert len(metadata["history_snapshot_ids"]) == len(metadata["history_revision_ids"])


def test_recording_stride_does_not_change_shared_signal_result() -> None:
    prepared = _prepared()
    dense = _replay(prepared, end=24, include_signals=True, record_every=1)
    sparse = _replay(prepared, end=24, include_signals=True, record_every=2)
    dense_point = dense.output_at("1h", 22)
    sparse_point = sparse.output_at("1h", 22)
    assert dense_point.output.signal_output == sparse_point.output.signal_output
    assert dense_point.replay_point_id == sparse_point.replay_point_id


def test_warmup_window_changes_replay_identity() -> None:
    prepared = _prepared()
    first = _replay(prepared, warmup=19, end=22)
    second = _replay(prepared, warmup=20, end=22)
    assert first.replay_id != second.replay_id


def test_multiple_timeframes_replay_independently_in_requested_order() -> None:
    prepared = _prepared(timeframes=("1h", "2h"))
    replay = _replay(prepared, end=22)
    assert tuple(replay.timeframes) == ("1h", "2h")
    assert replay.timeframes["1h"].recorded_positions == (20, 21, 22)
    assert replay.timeframes["2h"].recorded_positions == (20, 21, 22)


def test_invalid_model_output_position_remains_recordable() -> None:
    replay = _replay(_prepared(), end=19, warmup=19, record_start=19)
    point = replay.output_at("1h", 19)
    assert point.output.fit_result.is_valid is False
    assert replay.timeframes["1h"].recorded_positions == (19,)


def test_replay_point_nested_mutation_is_detected_by_output_at() -> None:
    replay = _replay(_prepared(), end=22)
    point = replay.output_at("1h", 22)
    point.boundary_snapshot.boundary.interaction = "MUTATED_AFTER_ID"
    with pytest.raises(TrendlineReplayIntegrityError):
        replay.output_at("1h", 22)


def test_identical_runs_have_stable_content_and_point_ids() -> None:
    prepared = _prepared()
    left = _replay(prepared, end=22)
    right = _replay(prepared, end=22)
    left_point = left.output_at("1h", 22)
    right_point = right.output_at("1h", 22)
    assert left_point.content_id == right_point.content_id
    assert left_point.replay_point_id == right_point.replay_point_id


def test_independent_truncation_preserves_shared_point_content_identity() -> None:
    full_prepared = _prepared()
    full_frame = full_prepared.dataset.frames["1h"]
    truncated_frame = full_frame.iloc[:24].copy()
    truncated_frame.attrs = dict(full_frame.attrs)
    truncated_prepared = _injected_prepared(
        {"1h": truncated_frame},
        timeframes=("1h",),
    )
    full = _replay(full_prepared, end=27)
    truncated = _replay(truncated_prepared, end=23)
    full_point = full.output_at("1h", 22)
    truncated_point = truncated.output_at("1h", 22)
    assert full_point.content_id == truncated_point.content_id
    assert full_point.replay_point_id == truncated_point.replay_point_id


def test_summary_extrema_are_global_across_timeframe_order() -> None:
    base = _prepared(timeframes=("4h", "1h"))
    frames: dict[str, pd.DataFrame] = {}
    for timeframe, frame in base.dataset.frames.items():
        shifted = frame.copy()
        shifted.attrs = dict(frame.attrs)
        if timeframe == "4h":
            shifted.index = shifted.index + pd.Timedelta(days=2)
            shifted["bar_available_at"] = pd.DatetimeIndex(
                shifted["bar_available_at"]
            ) + pd.Timedelta(days=2)
        frames[timeframe] = shifted
    prepared = _injected_prepared(frames, timeframes=("4h", "1h"))
    replay = _replay(prepared, end=22)
    from libs.models.trendlines.workflows.research import replay_snapshot_rows, replay_summary

    rows = replay_snapshot_rows(replay)
    summary = replay_summary(replay)
    assert summary.first_event_at == min(row.event_at for row in rows)
    assert summary.last_event_at == max(row.event_at for row in rows)
    assert summary.first_available_at == min(row.available_at for row in rows)
    assert summary.last_available_at == max(row.available_at for row in rows)


__all__ = []
