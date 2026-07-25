"""Contracts for deterministic trendline source and snapshot identities."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from libs.models.trendlines import (
    PivotFinality,
    SourceIdentityKind,
    TrendlineExecutionMode,
    TrendlineSnapshotFinality,
    TrendlineSnapshotStage,
    TrendlineSourceRef,
    fit_and_signal,
    fit_trendlines,
    fit_trendlines_to_boundary,
)
from libs.models.trendlines.contracts.identity import (
    canonical_json,
    canonical_point_text,
    resolve_source_ref,
)
from libs.models.trendlines.pipeline import orchestrator as pipeline_orchestrator


def _frame(rows: int = 96) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=rows, freq="h")
    x = np.linspace(0.0, 12.0, rows)
    close = 100.0 + 0.08 * np.arange(rows) + 2.0 * np.sin(x)
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 0.6,
            "low": close - 0.6,
            "close": close,
            "volume": np.linspace(1.0, 2.0, rows),
        },
        index=index,
    )


def test_empty_frame_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        fit_trendlines(_frame(0))


def test_non_monotonic_frame_index_is_rejected() -> None:
    frame = _frame()
    frame.index = frame.index[::-1]
    with pytest.raises(ValueError, match="monotonic"):
        fit_trendlines(frame)


def test_duplicate_frame_index_is_rejected() -> None:
    frame = _frame()
    values = list(frame.index)
    values[10] = values[9]
    frame.index = pd.DatetimeIndex(values)
    with pytest.raises(ValueError, match="unique"):
        fit_trendlines(frame)


def test_as_of_is_derived_from_final_index() -> None:
    frame = _frame()
    output = fit_trendlines(frame)
    assert output.checkpoint is not None
    assert output.checkpoint.source.as_of == canonical_point_text(frame.index[-1])


def test_explicit_matching_as_of_is_accepted() -> None:
    frame = _frame()
    output = fit_trendlines(frame, as_of=frame.index[-1])
    assert output.checkpoint is not None
    assert output.checkpoint.source.as_of == canonical_point_text(frame.index[-1])


def test_explicit_earlier_as_of_is_rejected() -> None:
    frame = _frame()
    with pytest.raises(ValueError, match="final supplied frame index"):
        fit_trendlines(frame, as_of=frame.index[-2])


def test_explicit_future_as_of_is_rejected() -> None:
    frame = _frame()
    with pytest.raises(ValueError, match="final supplied frame index"):
        fit_trendlines(frame, as_of=frame.index[-1] + pd.Timedelta(hours=1))


def test_computed_source_identity_is_stable_for_identical_frames() -> None:
    first = fit_trendlines(_frame())
    second = fit_trendlines(_frame())
    assert first.checkpoint is not None
    assert second.checkpoint is not None
    assert first.checkpoint.source.source_id == second.checkpoint.source.source_id


def test_revising_an_earlier_ohlcv_value_changes_source_identity() -> None:
    first_frame = _frame()
    second_frame = first_frame.copy()
    second_frame.iloc[12, second_frame.columns.get_loc("close")] += 0.75
    first = fit_trendlines(first_frame)
    second = fit_trendlines(second_frame)
    assert first.checkpoint is not None
    assert second.checkpoint is not None
    assert first.checkpoint.source.source_id != second.checkpoint.source.source_id


def test_provided_source_reference_validates_horizon_without_frame_hashing() -> None:
    frame = _frame()
    computed = resolve_source_ref(frame)
    provided = TrendlineSourceRef(
        source_id="upstream-manifest-42",
        source_start=computed.source_start,
        as_of=computed.as_of,
        row_count=computed.row_count,
        columns=computed.columns,
        identity_kind=SourceIdentityKind.PROVIDED,
    )
    with patch(
        "libs.models.trendlines.contracts.identity.compute_source_id",
        side_effect=AssertionError("provided source path hashed frame"),
    ):
        output = fit_trendlines(frame, source_ref=provided)
    assert output.checkpoint is not None
    assert output.checkpoint.source == provided


def test_identical_execution_produces_stable_checkpoint_id() -> None:
    first = fit_trendlines(_frame())
    second = fit_trendlines(_frame())
    assert first.checkpoint is not None
    assert second.checkpoint is not None
    assert first.checkpoint.checkpoint_id == second.checkpoint.checkpoint_id


def test_behaviour_affecting_config_changes_checkpoint_id() -> None:
    frame = _frame()
    first = fit_trendlines(frame, extractor_kwargs={"window_left": 2, "window_right": 2})
    second = fit_trendlines(frame, extractor_kwargs={"window_left": 3, "window_right": 3})
    assert first.checkpoint is not None
    assert second.checkpoint is not None
    assert first.checkpoint.checkpoint_id != second.checkpoint.checkpoint_id


def test_runtime_fractal_maps_to_confirmed_as_of() -> None:
    output = fit_trendlines(_frame())
    assert output.checkpoint is not None
    assert output.snapshot_identity is not None
    assert output.checkpoint.execution_mode is TrendlineExecutionMode.RUNTIME
    assert output.checkpoint.extractor_finality is PivotFinality.CONFIRMED_APPEND_ONLY
    assert output.snapshot_identity.finality is TrendlineSnapshotFinality.CONFIRMED_AS_OF


def test_research_rdp_maps_to_retrospective_revising() -> None:
    output = fit_trendlines(
        _frame(),
        extractor="rdp_zigzag",
        execution_mode=TrendlineExecutionMode.RESEARCH,
        extractor_kwargs={"epsilon_atr": 0.1, "min_segment_bars": 1},
    )
    assert output.checkpoint is not None
    assert output.snapshot_identity is not None
    assert output.checkpoint.execution_mode is TrendlineExecutionMode.RESEARCH
    assert output.checkpoint.extractor_finality is PivotFinality.RETROSPECTIVE_PREFIX_REVISING
    assert output.snapshot_identity.finality is TrendlineSnapshotFinality.RETROSPECTIVE_REVISING


def test_identical_fit_execution_produces_stable_snapshot_and_revision_ids() -> None:
    first = fit_trendlines(_frame())
    second = fit_trendlines(_frame())
    assert first.snapshot_identity is not None
    assert second.snapshot_identity is not None
    assert first.snapshot_identity.snapshot_id == second.snapshot_identity.snapshot_id
    assert first.snapshot_identity.revision_id == second.snapshot_identity.revision_id


def test_same_scoped_as_of_with_changed_source_changes_only_revision_id() -> None:
    first_frame = _frame()
    second_frame = first_frame.copy()
    second_frame.iloc[12, second_frame.columns.get_loc("close")] += 0.75
    first = fit_trendlines(first_frame, asset="BTCUSDT", timeframe="1h")
    second = fit_trendlines(second_frame, asset="BTCUSDT", timeframe="1h")
    assert first.snapshot_identity is not None
    assert second.snapshot_identity is not None
    assert first.snapshot_identity.snapshot_id == second.snapshot_identity.snapshot_id
    assert first.snapshot_identity.revision_id != second.snapshot_identity.revision_id


def test_boundary_facade_attaches_boundary_stage_identity() -> None:
    output = fit_trendlines_to_boundary(_frame(), asset="BTCUSDT", timeframe="1h")
    assert output.snapshot_identity is not None
    assert output.boundary_result is not None
    assert output.snapshot_identity.stage is TrendlineSnapshotStage.BOUNDARY
    assert output.boundary_result.snapshot_identity == output.snapshot_identity
    assert output.boundary_result.snapshot_identity is not None
    assert output.boundary_result.snapshot_identity.checkpoint is output.checkpoint


def test_signal_facade_attaches_signal_stage_and_retains_boundary_stage() -> None:
    output = fit_and_signal(_frame(), asset="BTCUSDT", timeframe="1h")
    assert output.snapshot_identity is not None
    assert output.boundary_result is not None
    assert output.snapshot_identity.stage is TrendlineSnapshotStage.SIGNAL
    assert output.boundary_result.snapshot_identity is not None
    assert output.boundary_result.snapshot_identity.stage is TrendlineSnapshotStage.BOUNDARY
    assert output.boundary_result.snapshot_identity.checkpoint is output.checkpoint


def test_to_dict_serializes_identity_fields_deterministically() -> None:
    output = fit_and_signal(_frame(), asset="BTCUSDT", timeframe="1h")
    first = output.to_dict()
    second = output.to_dict()
    assert first["checkpoint"] is not None
    assert first["snapshot_identity"] is not None
    assert first["fit_result"]["checkpoint"] is not None
    assert canonical_json(first) == canonical_json(second)


def test_full_facade_resolves_source_reference_exactly_once() -> None:
    frame = _frame()
    from libs.models.trendlines.contracts.identity import resolve_source_ref as resolve

    with patch.object(
        pipeline_orchestrator,
        "resolve_source_ref",
        wraps=resolve,
    ) as resolver:
        output = fit_and_signal(frame, asset="BTCUSDT", timeframe="1h")
    assert resolver.call_count == 1
    assert output.checkpoint is not None
