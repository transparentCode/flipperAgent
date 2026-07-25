from __future__ import annotations

from datetime import datetime, timezone

from libs.models.trendlines.config import TrendlinesConfig
from libs.models.trendlines.boundary import BoundaryResult
from libs.models.trendlines.signals import AlphaSignal, TrendlineSignalOrchestrator


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
    return BoundaryResult(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        is_valid=True,
    )


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

    output = orchestrator.run(_make_boundary_result())

    assert output["composite_direction"] == 0.3333
    assert output["composite_confidence"] == 1.0
    assert {signal.source for signal in output["signals"]} == {"bullish", "bearish"}