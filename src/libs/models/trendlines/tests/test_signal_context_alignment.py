from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pandas as pd
import pytest

from libs.models.trendlines.boundary import BoundaryResult, TrendlineSnapshot
from libs.models.trendlines.contracts.identity import (
    PivotFinality,
    SourceIdentityKind,
    TrendlineCheckpoint,
    TrendlineExecutionMode,
    TrendlineSnapshotStage,
    TrendlineSourceRef,
    build_snapshot_identity,
)
from libs.models.trendlines.signals.context import (
    BarAvailabilitySource,
    BarTimestampSemantics,
    SignalAvailabilityError,
    SignalContextContractError,
    SignalHistoryContractError,
    TrendlineSignalContext,
    TrendlineSignalInputs,
    validate_signal_inputs,
)
from libs.models.trendlines.signals.orchestrator import TrendlineSignalOrchestrator


_START = pd.Timestamp("2026-01-01T00:00:00Z")


def _event(hour: int) -> datetime:
    return (_START + pd.Timedelta(hours=hour)).to_pydatetime()


def _frame(start: int = 8, count: int = 3) -> pd.DataFrame:
    index = pd.date_range(_event(start), periods=count, freq="h")
    return pd.DataFrame(
        {
            "open": [100.0 + offset for offset in range(count)],
            "high": [101.0 + offset for offset in range(count)],
            "low": [99.0 + offset for offset in range(count)],
            "close": [100.5 + offset for offset in range(count)],
            "volume": [1000.0 + offset for offset in range(count)],
        },
        index=index,
    )


def _boundary(
    hour: int,
    *,
    asset: str = "BTCUSDT",
    timeframe: str = "1h",
    snapshot_id: str | None = None,
    revision_id: str | None = None,
) -> BoundaryResult:
    timestamp = _event(hour)
    source = TrendlineSourceRef(
        source_id=f"source-{asset}-{timeframe}-{hour}-{revision_id or 'base'}",
        source_start=_event(max(hour - 2, 0)).isoformat(),
        as_of=timestamp.isoformat(),
        row_count=3,
        columns=("open", "high", "low", "close", "volume"),
        identity_kind=SourceIdentityKind.COMPUTED,
    )
    checkpoint = TrendlineCheckpoint(
        checkpoint_id=f"checkpoint-{asset}-{timeframe}-{hour}-{revision_id or 'base'}",
        source=source,
        config_id="config-signal-context",
        execution_mode=TrendlineExecutionMode.RUNTIME,
        extractor_finality=PivotFinality.CONFIRMED_APPEND_ONLY,
    )
    identity = build_snapshot_identity(
        checkpoint=checkpoint,
        stage=TrendlineSnapshotStage.BOUNDARY,
        content_payload={"revision": revision_id or "base"},
        asset=asset,
        timeframe=timeframe,
    )
    if snapshot_id is not None:
        identity = type(identity)(
            snapshot_id=snapshot_id,
            revision_id=revision_id or identity.revision_id,
            checkpoint=identity.checkpoint,
            stage=identity.stage,
            finality=identity.finality,
            content_id=identity.content_id,
            asset=identity.asset,
            timeframe=identity.timeframe,
        )
    return BoundaryResult(
        asset=asset,
        timeframe=timeframe,
        timestamp=timestamp,
        is_valid=True,
        snapshot_identity=identity,
    )


def _snapshot(boundary: BoundaryResult, *, known_at: datetime | None = None) -> TrendlineSnapshot:
    return TrendlineSnapshot.from_boundary(boundary, known_at=known_at)


def _context(
    frame: pd.DataFrame,
    *,
    known_at: datetime | None = None,
    available: pd.DatetimeIndex | None = None,
    semantics: BarTimestampSemantics = BarTimestampSemantics.CLOSE_TIME,
) -> TrendlineSignalContext:
    availability = available if available is not None else frame.index
    return TrendlineSignalContext(
        known_at=known_at or frame.index[-1].to_pydatetime(),
        bar_available_at=availability,
        timestamp_semantics=semantics,
        volume_is_trustworthy=True,
        availability_source=(
            BarAvailabilitySource.CLOSE_TIME_INDEX
            if semantics is BarTimestampSemantics.CLOSE_TIME
            else BarAvailabilitySource.FIXED_INTERVAL_DERIVED
        ),
    )


def test_valid_close_time_context_is_accepted():
    frame = _frame()
    current = _boundary(10)
    validated = validate_signal_inputs(
        frame,
        current,
        TrendlineSignalInputs(context=_context(frame)),
    )
    assert validated.history_boundaries == ()
    assert validated.signal_available_at == frame.index[-1].to_pydatetime()


def test_naive_context_known_at_is_rejected():
    frame = _frame()
    with pytest.raises(SignalContextContractError, match="known_at"):
        TrendlineSignalContext(
            known_at=datetime(2026, 1, 1, 10),
            bar_available_at=frame.index,
            timestamp_semantics=BarTimestampSemantics.CLOSE_TIME,
            volume_is_trustworthy=True,
        )


def test_availability_length_mismatch_is_rejected():
    frame = _frame()
    context = _context(frame, available=frame.index[:-1])
    with pytest.raises(SignalContextContractError, match="length"):
        validate_signal_inputs(
            frame,
            _boundary(10),
            TrendlineSignalInputs(context=context),
        )


def test_non_monotonic_availability_is_rejected():
    frame = _frame()
    with pytest.raises(SignalContextContractError, match="monotonic"):
        _context(frame, available=pd.DatetimeIndex([frame.index[0], frame.index[2], frame.index[1]]))


def test_duplicate_availability_is_rejected():
    frame = _frame()
    with pytest.raises(SignalContextContractError, match="unique"):
        _context(frame, available=pd.DatetimeIndex([frame.index[0], frame.index[1], frame.index[1]]))


def test_availability_before_event_time_is_rejected():
    frame = _frame()
    available = frame.index - pd.Timedelta(minutes=1)
    context = _context(frame, available=available)
    with pytest.raises(SignalAvailabilityError, match="precede"):
        validate_signal_inputs(
            frame,
            _boundary(10),
            TrendlineSignalInputs(context=context),
        )


def test_bar_unavailable_at_query_knowledge_time_is_rejected():
    frame = _frame()
    with pytest.raises(SignalAvailabilityError, match="known_at"):
        TrendlineSignalContext(
            known_at=(frame.index[-1] - pd.Timedelta(minutes=1)).to_pydatetime(),
            bar_available_at=frame.index,
            timestamp_semantics=BarTimestampSemantics.CLOSE_TIME,
            volume_is_trustworthy=True,
        )


def test_current_frame_boundary_timestamp_mismatch_is_rejected():
    frame = _frame()
    with pytest.raises(SignalContextContractError, match="final event"):
        validate_signal_inputs(
            frame,
            _boundary(11),
            TrendlineSignalInputs(context=_context(frame)),
        )


def test_raw_boundary_history_is_rejected():
    frame = _frame()
    with pytest.raises(SignalHistoryContractError, match="TrendlineSnapshot"):
        TrendlineSignalInputs(
            context=_context(frame),
            history=(_boundary(9),),  # type: ignore[arg-type]
        )


def test_history_with_wrong_asset_is_rejected():
    frame = _frame()
    history = (_snapshot(_boundary(9, asset="ETHUSDT")),)
    with pytest.raises(SignalHistoryContractError, match="asset"):
        validate_signal_inputs(
            frame,
            _boundary(10),
            TrendlineSignalInputs(context=_context(frame), history=history),
        )


def test_history_with_wrong_timeframe_is_rejected():
    frame = _frame()
    history = (_snapshot(_boundary(9, timeframe="4h")),)
    with pytest.raises(SignalHistoryContractError, match="timeframe"):
        validate_signal_inputs(
            frame,
            _boundary(10),
            TrendlineSignalInputs(context=_context(frame), history=history),
        )


def test_unordered_history_is_rejected():
    frame = _frame()
    history = (_snapshot(_boundary(9)), _snapshot(_boundary(8)))
    with pytest.raises(SignalHistoryContractError, match="increasing"):
        validate_signal_inputs(
            frame,
            _boundary(10),
            TrendlineSignalInputs(context=_context(frame), history=history),
        )


def test_duplicate_logical_history_is_rejected():
    frame = _frame()
    snapshot = _snapshot(_boundary(9, snapshot_id="logical-9", revision_id="revision-9"))
    with pytest.raises(SignalHistoryContractError, match="duplicate snapshot"):
        validate_signal_inputs(
            frame,
            _boundary(10),
            TrendlineSignalInputs(context=_context(frame), history=(snapshot, snapshot)),
        )


def test_future_event_history_is_rejected():
    frame = _frame()
    history = (_snapshot(_boundary(11)),)
    with pytest.raises(SignalHistoryContractError, match="precede"):
        validate_signal_inputs(
            frame,
            _boundary(10),
            TrendlineSignalInputs(context=_context(frame), history=history),
        )


def test_future_known_history_revision_is_rejected():
    frame = _frame()
    history = (
        _snapshot(
            _boundary(9),
            known_at=(frame.index[-1] + pd.Timedelta(hours=1)).to_pydatetime(),
        ),
    )
    with pytest.raises(SignalHistoryContractError, match="known"):
        validate_signal_inputs(
            frame,
            _boundary(10),
            TrendlineSignalInputs(context=_context(frame), history=history),
        )


def test_valid_causal_history_unwraps_in_event_time_order():
    frame = _frame()
    snapshots = (
        _snapshot(_boundary(8), known_at=_event(8)),
        _snapshot(_boundary(9), known_at=_event(9)),
    )
    validated = validate_signal_inputs(
        frame,
        _boundary(10),
        TrendlineSignalInputs(context=_context(frame), history=snapshots),
    )
    assert [boundary.timestamp.hour for boundary in validated.history_boundaries] == [8, 9]


def test_identical_inputs_produce_stable_signal_input_id():
    frame = _frame()
    current = _boundary(10)
    inputs = TrendlineSignalInputs(context=_context(frame))
    first = validate_signal_inputs(frame, current, inputs)
    second = validate_signal_inputs(frame, current, inputs)
    assert first.signal_input_id == second.signal_input_id


def test_changed_selected_history_revision_changes_signal_and_signal_revision_ids():
    frame = _frame()
    current = _boundary(10)
    first_revision = _snapshot(
        _boundary(9, snapshot_id="logical-9", revision_id="revision-a"),
        known_at=_event(9),
    )
    second_revision = _snapshot(
        _boundary(9, snapshot_id="logical-9", revision_id="revision-b"),
        known_at=_event(9),
    )
    first = validate_signal_inputs(
        frame,
        current,
        TrendlineSignalInputs(context=_context(frame), history=(first_revision,)),
    )
    second = validate_signal_inputs(
        frame,
        current,
        TrendlineSignalInputs(context=_context(frame), history=(second_revision,)),
    )
    first_signal = build_snapshot_identity(
        checkpoint=current.snapshot_identity.checkpoint,
        stage=TrendlineSnapshotStage.SIGNAL,
        content_payload={"signal_input_id": first.signal_input_id},
        asset="BTCUSDT",
        timeframe="1h",
    )
    second_signal = build_snapshot_identity(
        checkpoint=current.snapshot_identity.checkpoint,
        stage=TrendlineSnapshotStage.SIGNAL,
        content_payload={"signal_input_id": second.signal_input_id},
        asset="BTCUSDT",
        timeframe="1h",
    )
    assert first.signal_input_id != second.signal_input_id
    assert first_signal.revision_id != second_signal.revision_id


def test_exported_orchestrator_rejects_missing_frame():
    frame = _frame()
    current = _boundary(10)
    inputs = TrendlineSignalInputs(context=_context(frame))

    with pytest.raises(SignalContextContractError, match="frame"):
        TrendlineSignalOrchestrator().run(  # type: ignore[arg-type]
            current,
            signal_inputs=inputs,
            frame=None,
        )


def test_identityless_current_boundary_is_rejected():
    frame = _frame()
    identityless = BoundaryResult(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=_event(10),
        is_valid=True,
    )

    with pytest.raises(SignalContextContractError, match="identity"):
        validate_signal_inputs(
            frame,
            identityless,
            TrendlineSignalInputs(context=_context(frame)),
        )


def test_wrong_current_boundary_stage_scope_and_horizon_are_rejected():
    frame = _frame()
    inputs = TrendlineSignalInputs(context=_context(frame))

    wrong_stage = _boundary(10)
    wrong_stage.snapshot_identity = replace(
        wrong_stage.snapshot_identity,
        stage=TrendlineSnapshotStage.SIGNAL,
    )
    with pytest.raises(SignalContextContractError, match="boundary-stage"):
        validate_signal_inputs(frame, wrong_stage, inputs)

    wrong_scope = _boundary(10)
    wrong_scope.snapshot_identity = replace(
        wrong_scope.snapshot_identity,
        asset="ETHUSDT",
    )
    with pytest.raises(SignalContextContractError, match="asset"):
        validate_signal_inputs(frame, wrong_scope, inputs)

    wrong_horizon = _boundary(10)
    wrong_source = replace(
        wrong_horizon.snapshot_identity.checkpoint.source,
        as_of=_event(9).isoformat(),
    )
    wrong_checkpoint = replace(
        wrong_horizon.snapshot_identity.checkpoint,
        source=wrong_source,
    )
    wrong_horizon.snapshot_identity = replace(
        wrong_horizon.snapshot_identity,
        checkpoint=wrong_checkpoint,
    )
    with pytest.raises(SignalContextContractError, match="horizon"):
        validate_signal_inputs(frame, wrong_horizon, inputs)


def test_current_checkpoint_horizon_must_match_frame_shape_and_columns():
    frame = _frame()
    current = _boundary(10)
    inputs = TrendlineSignalInputs(context=_context(frame))
    source = current.snapshot_identity.checkpoint.source

    for changed_source in (
        replace(source, row_count=2),
        replace(source, source_start=_event(7).isoformat()),
        replace(source, columns=("close",)),
    ):
        checkpoint = replace(
            current.snapshot_identity.checkpoint,
            source=changed_source,
        )
        current.snapshot_identity = replace(
            current.snapshot_identity,
            checkpoint=checkpoint,
        )
        with pytest.raises(SignalContextContractError, match="checkpoint"):
            validate_signal_inputs(frame, current, inputs)
        current = _boundary(10)


def test_exact_frame_and_identity_produce_bound_signal_input_id():
    frame = _frame()
    current = _boundary(10)
    output = TrendlineSignalOrchestrator().run(
        current,
        signal_inputs=TrendlineSignalInputs(context=_context(frame)),
        frame=frame,
    )

    assert output["signal_input_id"]
    assert output["signal_checkpoint_id"] == (
        current.snapshot_identity.checkpoint.checkpoint_id
    )
    assert output["signal_source_id"] == current.snapshot_identity.checkpoint.source.source_id
