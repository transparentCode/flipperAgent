from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from libs.models.trendlines.config import TrendlinesConfig
from libs.models.trendlines.boundary import BoundaryResult
from libs.models.trendlines.contracts.identity import (
    PivotFinality,
    SourceIdentityKind,
    TrendlineCheckpoint,
    TrendlineExecutionMode,
    TrendlineSnapshotStage,
    TrendlineSourceRef,
    build_snapshot_identity,
)
from libs.models.trendlines.signals import (
    AlphaSignal,
    TrendlineSignalContext,
    TrendlineSignalInputs,
    TrendlineSignalOrchestrator,
)


class _StubExtractor:
    def __init__(self, name: str, direction: float, confidence: float):
        self.name = name
        self._direction = direction
        self._confidence = confidence

    def extract(self, result: BoundaryResult, history=None, context=None):
        del history, context
        return [
            AlphaSignal(
                name=f"{self.name}_signal",
                direction=self._direction,
                confidence=self._confidence,
                source=self.name,
                timeframe=result.timeframe,
            )
        ]


def _make_boundary_result() -> BoundaryResult:
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = BoundaryResult(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=timestamp,
        is_valid=True,
    )
    source = TrendlineSourceRef(
        source_id="test-source",
        source_start=timestamp.isoformat(),
        as_of=timestamp.isoformat(),
        row_count=1,
        columns=("close",),
        identity_kind=SourceIdentityKind.COMPUTED,
    )
    checkpoint = TrendlineCheckpoint(
        checkpoint_id="test-checkpoint",
        source=source,
        config_id="test-config",
        execution_mode=TrendlineExecutionMode.RUNTIME,
        extractor_finality=PivotFinality.CONFIRMED_APPEND_ONLY,
    )
    result.snapshot_identity = build_snapshot_identity(
        checkpoint=checkpoint,
        stage=TrendlineSnapshotStage.BOUNDARY,
        content_payload={"test": "orchestrator-config"},
        asset=result.asset,
        timeframe=result.timeframe,
    )
    result.__post_init__()
    return result


def test_trendline_signal_orchestrator_reads_weights_from_config():
    from dataclasses import replace
    config = replace(
        TrendlinesConfig(),
        signal_weights={"bullish": 2.0, "bearish": 1.0},
    )
    orchestrator = TrendlineSignalOrchestrator(
        extractors=[
            _StubExtractor("bullish", direction=1.0, confidence=1.0),
            _StubExtractor("bearish", direction=-1.0, confidence=1.0),
        ],
        trendlines_config=config,
    )

    frame = pd.DataFrame(
        {"close": [100.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-01-01T00:00:00Z")]),
    )
    output = orchestrator.run(
        _make_boundary_result(),
        signal_inputs=TrendlineSignalInputs(
            context=TrendlineSignalContext.from_close_time_index(
                frame.index,
                volume_is_trustworthy=False,
            )
        ),
        frame=frame,
    )

    assert output["composite_direction"] == 0.3333
    assert output["composite_confidence"] == 1.0
    assert {signal.source for signal in output["signals"]} == {"bullish", "bearish"}
