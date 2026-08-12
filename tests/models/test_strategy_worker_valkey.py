"""Tests for StrategyWorker.process_features() with Valkey encode/decode."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.signal_app.ohlcv_source import OhlcvSourceBinding
from apps.signal_app.pipeline.features import FeaturePipeline
from apps.signal_app.runtime.worker import SignalRuntimeWorker
from apps.signal_app.settings import SignalWorkerSettings
from apps.strategy_app.evaluation.service import StrategyEvaluationResult
from apps.strategy_app.settings import StrategyWorkerSettings
from apps.strategy_app.strategy_worker import StrategyWorker
from libs.contracts.schemas import (
    FeatureVector,
    ModelOutput,
    valkey_encode,
)
from libs.contracts.signal import ScoringOutput

_SIGNAL_SETTINGS = SignalWorkerSettings(
    ohlcv_sources=(
        OhlcvSourceBinding(
            asset="BTCUSDT",
            source="ingestion",
            venue="binance",
            instrument_id="BTC-USDT-PERP",
        ),
    )
)


def _v2_event(timestamp: float) -> dict[str, str]:
    open_time = datetime.fromtimestamp(timestamp, tz=UTC)
    payload = {
        "venue": "binance",
        "instrument_id": "BTC-USDT-PERP",
        "timeframe": "1m",
        "open_time": open_time.isoformat().replace("+00:00", "Z"),
        "close_time": (open_time + timedelta(minutes=1))
        .isoformat()
        .replace("+00:00", "Z"),
        "open": "100.0",
        "high": "101.0",
        "low": "99.0",
        "close": "100.5",
        "volume": "10.0",
        "taker_buy_base": "4.0",
        "source_type": "provider",
        "source_provider": "binance_native",
        "source_timeframe": None,
    }
    return {
        "event_id": f"test-{timestamp}",
        "event_type": "candle.committed",
        "schema_version": "1",
        "producer": "ingestion",
        "occurred_at": (open_time + timedelta(minutes=1, seconds=1))
        .isoformat()
        .replace("+00:00", "Z"),
        "payload": json.dumps(payload),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_feature_vector() -> FeatureVector:
    return FeatureVector(
        asset="BTCUSDT",
        timeframe="4h",
        timestamp=1_700_000_000.0,
        features={"RSI": {"value": 45.0}, "ATR": {"value": 500.0}},
        bar_data={
            "open": 49_000.0,
            "high": 51_000.0,
            "low": 48_500.0,
            "close": 50_000.0,
            "volume": 100.0,
        },
    )


def _make_model_output(direction: int = 1) -> ModelOutput:
    return ModelOutput(
        model_name="dual_ema",
        asset="BTCUSDT",
        timeframe="4h",
        timestamp=1_700_000_000.0,
        direction=direction,
        conviction=0.85,
        metadata={"score": 0.9},
    )


def _history(
    length: int = 8, timeframe_seconds: int = 14_400
) -> list[tuple[float, ...]]:
    start = 1_700_000_000 - length * timeframe_seconds
    rows: list[tuple[float, ...]] = []
    for index in range(length):
        ts = float(start + index * timeframe_seconds)
        price = 100.0 + index
        rows.append(
            (price, price + 1.0, price - 1.0, price + 0.5, 10.0 + index, ts, 4.0)
        )
    return rows


def _history_1m(length: int = 240) -> list[tuple[float, ...]]:
    start = 1_700_000_000 - length * 60
    rows: list[tuple[float, ...]] = []
    for index in range(length):
        ts = float(start + index * 60)
        price = 100.0 + (index * 0.05)
        rows.append(
            (price, price + 0.2, price - 0.2, price + 0.1, 5.0 + index, ts, 2.0)
        )
    return rows


class _FakeRawIndicators:
    def __init__(self, *, snapshot: dict[str, float], live: dict[str, float]) -> None:
        self.snapshot = snapshot
        self.live = live
        self.history: list[tuple[float, ...]] = []
        self.indicators = [SimpleNamespace(lookback_required=4)]

    def prime(self, history: list[tuple[float, ...]]) -> None:
        self.history = list(history)

    def get_unprimed_indicator_keys(self) -> list[str]:
        return []

    def snapshot_features(self, history: list[tuple[float, ...]]) -> dict[str, float]:
        return dict(self.snapshot)

    def snapshot_raw(
        self, history: list[tuple[float, ...]]
    ) -> dict[str, dict[str, float]]:
        return {name: {"value": value} for name, value in self.snapshot.items()}

    def update(self, row: tuple[float, ...]) -> None:
        self.history.append(row)

    def process_tick(self, data: tuple[float, ...]) -> dict[str, float]:
        self.history.append(data)
        return dict(self.live)

    def get_latest_raw(self) -> dict[str, dict[str, float]]:
        return {name: {"value": value} for name, value in self.live.items()}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStrategyWorkerProcessFeatures:
    @pytest.mark.asyncio
    @patch("apps.strategy_app.strategy_worker.ModelManager")
    @patch("apps.strategy_app.strategy_worker.UnifiedModelManager")
    async def test_process_features_publishes_signal(
        self, MockUnifiedMM, MockMM
    ) -> None:
        """Valid FeatureVector payload → model evaluates → xadd called with signal stream."""
        from apps.strategy_app.strategy_worker import StrategyWorker

        mock_mm = MagicMock()
        mock_mm.evaluate.return_value = [_make_model_output(direction=1)]
        MockMM.return_value = mock_mm
        mock_unified_mm = MagicMock()
        mock_unified_mm.evaluate.return_value = []
        MockUnifiedMM.return_value = mock_unified_mm

        worker = StrategyWorker("BTCUSDT", "4h")
        worker.redis_client = AsyncMock()

        fv = _make_feature_vector()
        payload = valkey_encode(fv)

        await worker.process_features(payload)

        mock_mm.evaluate.assert_called_once()
        worker.redis_client.xadd.assert_called_once()
        call_args = worker.redis_client.xadd.call_args
        assert call_args[0][0] == "signals:BTCUSDT:4h"

    @pytest.mark.asyncio
    @patch("apps.strategy_app.strategy_worker.ModelManager")
    @patch("apps.strategy_app.strategy_worker.UnifiedModelManager")
    async def test_process_features_flat_direction_no_publish(
        self, MockUnifiedMM, MockMM
    ) -> None:
        """When model returns direction=0, no signal should be published."""
        from apps.strategy_app.strategy_worker import StrategyWorker

        mock_mm = MagicMock()
        mock_mm.evaluate.return_value = [_make_model_output(direction=0)]
        MockMM.return_value = mock_mm
        mock_unified_mm = MagicMock()
        mock_unified_mm.evaluate.return_value = []
        MockUnifiedMM.return_value = mock_unified_mm

        worker = StrategyWorker("BTCUSDT", "4h")
        worker.redis_client = AsyncMock()

        fv = _make_feature_vector()
        payload = valkey_encode(fv)

        await worker.process_features(payload)

        mock_mm.evaluate.assert_called_once()
        worker.redis_client.xadd.assert_not_called()

    @pytest.mark.asyncio
    @patch("apps.strategy_app.strategy_worker.ModelManager")
    @patch("apps.strategy_app.strategy_worker.UnifiedModelManager")
    async def test_feature_decode_error_no_crash(self, MockUnifiedMM, MockMM) -> None:
        """Malformed payload should not crash; no xadd should be called."""
        from apps.strategy_app.strategy_worker import StrategyWorker

        mock_mm = MagicMock()
        MockMM.return_value = mock_mm
        mock_unified_mm = MagicMock()
        mock_unified_mm.evaluate.return_value = []
        MockUnifiedMM.return_value = mock_unified_mm

        worker = StrategyWorker("BTCUSDT", "4h")
        worker.redis_client = AsyncMock()

        # Pass a malformed payload missing required fields
        payload = {"garbage_key": "garbage_value"}

        await worker.process_features(payload)

        mock_mm.evaluate.assert_not_called()
        worker.redis_client.xadd.assert_not_called()

    @pytest.mark.asyncio
    @patch("apps.strategy_app.strategy_worker.ModelManager")
    @patch("apps.strategy_app.strategy_worker.ScoringModelManager")
    @patch("apps.strategy_app.strategy_worker.UnifiedModelManager")
    async def test_process_features_blender_maps_runtime_model_names_and_publishes(
        self,
        MockUnifiedMM,
        MockSMM,
        MockMM,
    ) -> None:
        """Real runtime model names should still participate in blender weighting."""
        from apps.strategy_app.strategy_worker import StrategyWorker

        mock_mm = MagicMock()
        mock_mm.evaluate.return_value = []
        mock_mm.evaluate_adapted.return_value = [
            ScoringOutput(
                model_name="SqueezeBreakout",
                asset="BTCUSDT",
                timeframe="1h",
                timestamp=1_700_000_000.0,
                edge_score=0.4,
                conviction=0.8,
            )
        ]
        mock_mm.evaluate_scoring.return_value = [
            ScoringOutput(
                model_name="MeanReversion",
                asset="BTCUSDT",
                timeframe="1h",
                timestamp=1_700_000_000.0,
                edge_score=0.6,
                conviction=0.9,
            )
        ]
        mock_mm.evaluate_shadow.return_value = []
        MockMM.return_value = mock_mm

        mock_smm = MagicMock()
        mock_smm.evaluate.return_value = []
        MockSMM.return_value = mock_smm
        mock_unified_mm = MagicMock()
        mock_unified_mm.evaluate.return_value = []
        MockUnifiedMM.return_value = mock_unified_mm

        worker = StrategyWorker(
            "BTCUSDT",
            "1h",
            settings=StrategyWorkerSettings(
                blender_enabled=True,
                blender_config={
                    "transition": {"entry_threshold": 0.70, "exit_threshold": 0.30},
                    "mtf": {"confirming_scale": 1.2, "conflicting_scale": 0.5},
                    "weights": {
                        "TREND_BEAR": {
                            "mean_reversion": 0.49,
                            "squeeze_breakout": 0.51,
                        }
                    },
                },
            ),
        )
        worker.redis_client = AsyncMock()

        fv = FeatureVector(
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1_700_000_000.0,
            features={
                "regime_snapshot": {
                    "regime": "VOLATILE_TREND_BEAR",
                    "changepoint_prob": 0.05,
                }
            },
            bar_data={
                "open": 49_000.0,
                "high": 51_000.0,
                "low": 48_500.0,
                "close": 50_000.0,
                "volume": 100.0,
            },
        )

        await worker.process_features(valkey_encode(fv))

        worker.redis_client.xadd.assert_called_once()

    @pytest.mark.asyncio
    @patch("apps.strategy_app.strategy_worker.ModelManager")
    @patch("apps.strategy_app.strategy_worker.UnifiedModelManager")
    async def test_process_features_shadow_comparison_logging_does_not_break_publish(
        self,
        MockUnifiedMM,
        MockMM,
    ) -> None:
        """Structured comparison logging should not raise and poison the message."""
        from apps.strategy_app.strategy_worker import StrategyWorker

        mock_mm = MagicMock()
        mock_mm.evaluate.return_value = []
        mock_mm.evaluate_adapted.return_value = [
            ScoringOutput(
                model_name="SqueezeBreakout",
                asset="BTCUSDT",
                timeframe="4h",
                timestamp=1_700_000_000.0,
                edge_score=0.85,
                conviction=0.85,
            )
        ]
        mock_mm.evaluate_scoring.return_value = []
        mock_mm.evaluate_shadow.return_value = [
            ModelOutput(
                model_name="SqueezeBreakout",
                asset="BTCUSDT",
                timeframe="4h",
                timestamp=1_700_000_000.0,
                direction=1,
                conviction=0.85,
                metadata={},
            )
        ]
        MockMM.return_value = mock_mm
        mock_unified_mm = MagicMock()
        mock_unified_mm.evaluate.return_value = []
        MockUnifiedMM.return_value = mock_unified_mm

        worker = StrategyWorker("BTCUSDT", "4h")
        worker.redis_client = AsyncMock()

        await worker.process_features(valkey_encode(_make_feature_vector()))

        worker.redis_client.xadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_features_preserves_projected_source_lane_metadata(
        self,
    ) -> None:
        signal_redis = AsyncMock()
        signal_redis.xadd = AsyncMock(return_value="1-0")
        signal_redis.hset = AsyncMock(return_value=1)
        signal_redis.hgetall = AsyncMock(return_value={})
        raw = _FakeRawIndicators(snapshot={"RSI": 55.0}, live={"RSI": 56.0})
        pipeline = FeaturePipeline(raw_indicators=raw)
        signal_worker = SignalRuntimeWorker(
            "BTCUSDT",
            "4h",
            pipeline=pipeline,
            settings=_SIGNAL_SETTINGS,
            trigger_timeframe="1m",
            trigger_mode="on_base_bar_close",
            required_context_profiles=["volatility_15m"],
        )
        await signal_worker.connect(signal_redis)
        history_4h = _history(length=8)
        history_1m = _history_1m(length=240)
        signal_worker._prime_projection_history(history_4h)
        signal_worker._prime_source_history(history_1m)
        signal_worker._prime_ltf_history(history_1m)

        await signal_worker.process_message(
            "1-0",
            _v2_event(history_1m[-1][5] + 60),
        )

        published_payload = signal_redis.xadd.await_args_list[0].args[1]
        strategy_worker = StrategyWorker(
            "BTCUSDT",
            "4h",
            trigger_timeframe="1m",
            trigger_mode="on_base_bar_close",
        )
        strategy_worker.redis_client = AsyncMock()
        strategy_worker.signal_publisher.publish_selected = AsyncMock(return_value=0)
        strategy_worker._is_paused = AsyncMock(return_value=False)
        strategy_worker._update_runtime_state = AsyncMock()
        captured: dict[str, object] = {}

        def _evaluate(
            feature_vec: FeatureVector,
            *,
            allowed_model_names=None,
            runtime_metadata=None,
        ):
            captured["feature_vec"] = feature_vec
            captured["runtime_metadata"] = runtime_metadata
            return StrategyEvaluationResult(feature_vector=feature_vec, selected=[])

        strategy_worker.evaluation_service = SimpleNamespace(
            evaluate_feature_vector_routed=_evaluate
        )

        await strategy_worker.process_features(published_payload)

        runtime_metadata = captured["runtime_metadata"]
        assert runtime_metadata is not None
        assert runtime_metadata["decision_timeframe"] == "4h"
        assert runtime_metadata["trigger_timeframe"] == "1m"
        assert runtime_metadata["source_feature_timeframe"] == "1m"
        assert runtime_metadata["trigger_mode"] == "on_base_bar_close"
        assert runtime_metadata["projection_mode"] == "decision_view"
        assert runtime_metadata["decision_bar_closed"] is False

        feature_vec = captured["feature_vec"]
        assert feature_vec is not None
        transport = feature_vec.features["ctx_transport"]
        assert transport["source_feature_timeframe"] == "1m"
        assert transport["decision_timeframe"] == "4h"
        assert transport["projection_mode"] == "decision_view"
