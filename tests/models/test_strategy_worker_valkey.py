"""Tests for StrategyWorker.process_features() with Valkey encode/decode."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from libs.contracts.schemas import (
    FeatureVector,
    ModelOutput,
    TradeSignal,
    valkey_encode,
)
from libs.contracts.signal import ScoringOutput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_feature_vector() -> FeatureVector:
    return FeatureVector(
        asset="BTCUSDT",
        timeframe="4h",
        timestamp=1_700_000_000.0,
        features={"RSI": {"value": 45.0}, "ATR": {"value": 500.0}},
        bar_data={"open": 49_000.0, "high": 51_000.0, "low": 48_500.0, "close": 50_000.0, "volume": 100.0},
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStrategyWorkerProcessFeatures:
    @pytest.mark.asyncio
    @patch("apps.strategy_app.strategy_worker.ModelManager")
    async def test_process_features_publishes_signal(self, MockMM) -> None:
        """Valid FeatureVector payload → model evaluates → xadd called with signal stream."""
        from apps.strategy_app.strategy_worker import StrategyWorker

        mock_mm = MagicMock()
        mock_mm.evaluate.return_value = [_make_model_output(direction=1)]
        MockMM.return_value = mock_mm

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
    async def test_process_features_flat_direction_no_publish(self, MockMM) -> None:
        """When model returns direction=0, no signal should be published."""
        from apps.strategy_app.strategy_worker import StrategyWorker

        mock_mm = MagicMock()
        mock_mm.evaluate.return_value = [_make_model_output(direction=0)]
        MockMM.return_value = mock_mm

        worker = StrategyWorker("BTCUSDT", "4h")
        worker.redis_client = AsyncMock()

        fv = _make_feature_vector()
        payload = valkey_encode(fv)

        await worker.process_features(payload)

        mock_mm.evaluate.assert_called_once()
        worker.redis_client.xadd.assert_not_called()

    @pytest.mark.asyncio
    @patch("apps.strategy_app.strategy_worker.ModelManager")
    async def test_feature_decode_error_no_crash(self, MockMM) -> None:
        """Malformed payload should not crash; no xadd should be called."""
        from apps.strategy_app.strategy_worker import StrategyWorker

        mock_mm = MagicMock()
        MockMM.return_value = mock_mm

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
    async def test_process_features_blender_maps_runtime_model_names_and_publishes(
        self,
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

        worker = StrategyWorker("BTCUSDT", "1h")
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
            bar_data={"open": 49_000.0, "high": 51_000.0, "low": 48_500.0, "close": 50_000.0, "volume": 100.0},
        )

        await worker.process_features(valkey_encode(fv))

        worker.redis_client.xadd.assert_called_once()

    @pytest.mark.asyncio
    @patch("apps.strategy_app.strategy_worker.ModelManager")
    async def test_process_features_shadow_comparison_logging_does_not_break_publish(self, MockMM) -> None:
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

        worker = StrategyWorker("BTCUSDT", "4h")
        worker.redis_client = AsyncMock()

        await worker.process_features(valkey_encode(_make_feature_vector()))

        worker.redis_client.xadd.assert_called_once()
