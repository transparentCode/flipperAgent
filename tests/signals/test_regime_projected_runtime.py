from __future__ import annotations

from typing import ClassVar

import pytest

from apps.signal_app.ohlcv_source import OhlcvSourceBinding
from apps.signal_app.pipeline.features import FeaturePipeline
from apps.signal_app.pipeline.regime import RegimeFeaturePipeline
from apps.signal_app.runtime.worker import SignalRuntimeWorker
from apps.signal_app.settings import SignalWorkerSettings

_SETTINGS = SignalWorkerSettings(
    ohlcv_sources=(
        OhlcvSourceBinding(
            asset="BTCUSDT",
            source="ingestion",
            venue="binance",
            instrument_id="BTC-USDT-PERP",
        ),
    )
)


class _RawIndicators:
    indicators: ClassVar[list[object]] = []

    def __init__(self) -> None:
        self.prime_calls: list[list[tuple[float, ...]]] = []

    def prime(self, history) -> None:
        self.prime_calls.append(history)

    def get_unprimed_indicator_keys(self) -> list[str]:
        return []

    def snapshot_features(self, history) -> dict[str, float]:
        del history
        return {"RSI": 55.0}


class _ActiveRegimeV2:
    min_bars = 1

    def __init__(self) -> None:
        self.latest_features: list[dict[str, object]] = []

    def analyze(self, price_history, *, latest_features):
        self.latest_features.append(dict(latest_features))
        return {"active_price_history_bars": len(price_history), "signal": "unchanged"}


@pytest.mark.asyncio
async def test_projected_regime_history_advances_once_on_confirmed_decision_close() -> (
    None
):
    raw = _RawIndicators()
    active_regime = _ActiveRegimeV2()
    regime = RegimeFeaturePipeline(
        "BTCUSDT",
        "4h",
        min_bars=1,
        orchestrator=None,
        classifier=None,
        regime_v2=active_regime,
    )
    pipeline = FeaturePipeline(raw_indicators=raw, regime_features=regime)
    worker = SignalRuntimeWorker(
        "BTCUSDT",
        "4h",
        pipeline=pipeline,
        settings=_SETTINGS,
        trigger_timeframe="1h",
        trigger_mode="on_base_bar_close",
    )

    decision_history = _decision_history()
    regime.prime(decision_history)
    worker._prime_projection_history(decision_history)
    worker._prime_source_history([_source_bar(115_200.0)])

    observations: list[dict[str, int | bool]] = []
    for timestamp in (118_800.0, 122_400.0, 126_000.0, 129_600.0):
        worker._source_history.append(_source_bar(timestamp))
        projected = worker._current_projected_bar()
        assert projected is not None

        history_before = len(regime.price_history)
        feature_vector, _ = await worker._process_projected_candle(
            candle=worker._projected_candle_from_projection(projected),
            ltf_context_profiles=None,
        )
        history_after = len(regime.price_history)
        reported_history_length = int(
            feature_vector.features["regime_v2"]["active_price_history_bars"]
        )

        observations.append(
            {
                "closed": projected.closed,
                "history_before": history_before,
                "history_after": history_after,
                "reported_history_length": reported_history_length,
            }
        )
        assert history_after == history_before + int(projected.closed)
        assert reported_history_length == history_before
        assert "trendline_family_shadow" not in feature_vector.features

    assert any(observation["closed"] for observation in observations)
    assert any(not observation["closed"] for observation in observations)
    assert sum(int(observation["closed"]) for observation in observations) == 1
    close_index = next(
        index for index, observation in enumerate(observations) if observation["closed"]
    )
    assert (
        observations[close_index]["history_after"]
        == observations[close_index]["history_before"] + 1
    )
    assert (
        observations[close_index + 1]["history_before"]
        == observations[close_index]["history_after"]
    )
    assert (
        observations[close_index + 1]["reported_history_length"]
        == observations[close_index]["history_after"]
    )
    assert len(raw.prime_calls) == 1


def _decision_history() -> list[tuple[float, ...]]:
    return [
        (100.0, 101.0, 99.0, 100.0, 1_000.0, float(index * 14_400), 10.0)
        for index in range(8)
    ]


def _source_bar(timestamp: float) -> tuple[float, ...]:
    return (100.0, 101.0, 99.0, 100.0, 10.0, timestamp, 2.0)
