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
