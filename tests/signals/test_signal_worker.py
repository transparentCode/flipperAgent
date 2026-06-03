"""Tests for SignalWorker.process_message()."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from libs.common.config import ConfigManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_closed_bar_payload(
    timestamp: float = 1_700_000_000_000.0,
) -> dict[str, str]:
    return {
        "bar_closed": "true",
        "open": "49000.0",
        "high": "51000.0",
        "low": "48500.0",
        "close": "50000.0",
        "volume": "100.0",
        "timestamp": str(timestamp),
    }


def _make_open_bar_payload() -> dict[str, str]:
    return {
        "bar_closed": "false",
        "open": "49000.0",
        "high": "50500.0",
        "low": "48800.0",
        "close": "50200.0",
        "volume": "50.0",
        "timestamp": "1700000000000.0",
    }


MOCK_FEATURE_RESULTS = {"RSI": {"value": 45.0}, "ATR": {"value": 500.0}}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSignalWorkerProcessMessage:
    @pytest.mark.asyncio
    @patch("apps.signal_app.signal_worker.FeatureManager")
    async def test_process_message_closed_bar(self, MockFM) -> None:
        """Closed bar triggers feature computation and xadd on the feature stream."""
        from apps.signal_app.signal_worker import SignalWorker

        mock_fm = MagicMock()
        mock_fm.indicators = []
        mock_fm.process_tick.return_value = MOCK_FEATURE_RESULTS
        MockFM.return_value = mock_fm

        worker = SignalWorker("BTCUSDT", "4h")
        worker.redis_client = AsyncMock()
        worker.redis_client.hgetall.return_value = {}

        payload = _make_closed_bar_payload()
        await worker.process_message("msg-1", payload)

        mock_fm.process_tick.assert_called_once()
        assert worker.redis_client.xadd.call_count == 2
        calls = worker.redis_client.xadd.call_args_list
        assert calls[0][0][0] == "features:BTCUSDT:4h"
        assert calls[1][0][0] == "price_update:BTCUSDT:4h"

    @pytest.mark.asyncio
    @patch("apps.signal_app.signal_worker.FeatureManager")
    async def test_process_message_open_bar(self, MockFM) -> None:
        """Non-closed bars (bar_closed: false) should NOT trigger feature computation."""
        from apps.signal_app.signal_worker import SignalWorker

        mock_fm = MagicMock()
        mock_fm.indicators = []
        MockFM.return_value = mock_fm

        worker = SignalWorker("BTCUSDT", "4h")
        worker.redis_client = AsyncMock()
        worker.redis_client.hgetall.return_value = {}

        payload = _make_open_bar_payload()
        await worker.process_message("msg-2", payload)

        mock_fm.process_tick.assert_not_called()
        worker.redis_client.xadd.assert_not_called()

    @pytest.mark.asyncio
    @patch("apps.signal_app.signal_worker.FeatureManager")
    async def test_timestamp_ms_guard(self, MockFM) -> None:
        """Timestamps < 1e12 are converted to milliseconds (×1000)."""
        from apps.signal_app.signal_worker import SignalWorker

        mock_fm = MagicMock()
        mock_fm.indicators = []
        mock_fm.process_tick.return_value = MOCK_FEATURE_RESULTS
        MockFM.return_value = mock_fm

        worker = SignalWorker("BTCUSDT", "4h")
        worker.redis_client = AsyncMock()
        worker.redis_client.hgetall.return_value = {}

        # Use seconds-based timestamp (< 1e12)
        payload = _make_closed_bar_payload(timestamp=1_700_000_000.0)
        await worker.process_message("msg-3", payload)

        # The data_tuple passed to process_tick should have the ms-converted timestamp
        call_args = mock_fm.process_tick.call_args[0][0]
        timestamp_in_tuple = call_args[5]
        assert timestamp_in_tuple == 1_700_000_000_000  # converted to ms

    @pytest.mark.asyncio
    @patch("apps.signal_app.signal_worker.FeatureManager")
    async def test_process_message_raises_on_publish_failure(self, MockFM) -> None:
        """Operational failures should bubble so BaseStreamConsumer can avoid acking."""
        from apps.signal_app.signal_worker import SignalWorker

        mock_fm = MagicMock()
        mock_fm.indicators = []
        mock_fm.process_tick.return_value = MOCK_FEATURE_RESULTS
        MockFM.return_value = mock_fm

        worker = SignalWorker("BTCUSDT", "4h")
        worker.redis_client = AsyncMock()
        worker.redis_client.hgetall.return_value = {}
        worker.redis_client.xadd.side_effect = RuntimeError("stream publish failed")

        with pytest.raises(RuntimeError, match="stream publish failed"):
            await worker.process_message("msg-4", _make_closed_bar_payload())

    def test_worker_uses_runtime_tradingview_config(self, monkeypatch) -> None:
        """TradingView index keys should come from runtime config, not import-time defaults."""
        from apps.signal_app.signal_worker import SignalWorker

        ConfigManager.reset_singleton()
        config_mgr = ConfigManager()
        monkeypatch.setattr(config_mgr, "_load_configs", lambda trigger_callbacks=True: None)
        monkeypatch.setattr(ConfigManager, "register_file", lambda self, _: None)
        config_mgr._state = {
            "tradingview": {
                "indices": ["CRYPTOCAP:TOTAL3", "CRYPTOCAP:OTHERS.D"],
            }
        }

        worker = SignalWorker("BTCUSDT", "4h")
        assert worker._tv_index_keys == ["TOTAL3", "OTHERS.D"]

    @pytest.mark.asyncio
    @patch("apps.signal_app.signal_worker.FeatureManager")
    async def test_start_waits_in_warming_mode_until_history_available(self, MockFM) -> None:
        """Workers should stay alive during cold start and begin once enough history exists."""
        from apps.signal_app.signal_worker import SignalWorker

        indicator = MagicMock()
        indicator.lookback_required = 20

        mock_fm = MagicMock()
        mock_fm.indicators = [indicator]
        history = [(1.0, 2.0, 0.5, 1.5, 10.0, 1700000000.0)] * 20
        mock_fm.fetch_historical_db_records = AsyncMock(
            side_effect=[[], [], [], history]
        )
        mock_fm.get_unprimed_indicator_keys.return_value = []
        MockFM.return_value = mock_fm

        worker = SignalWorker("BTCUSDT", "4h")
        worker.run = AsyncMock()

        with patch("apps.signal_app.signal_worker.asyncio.sleep", new=AsyncMock()):
            await worker.start()

        assert mock_fm.fetch_historical_db_records.await_count == 4
        mock_fm.prime.assert_called_once_with(history)
        worker.run.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("apps.signal_app.signal_worker.FeatureManager")
    async def test_start_publishes_bootstrap_snapshot_from_history(self, MockFM) -> None:
        """Startup should publish one immediate snapshot from primed history."""
        from apps.signal_app.signal_worker import SignalWorker

        indicator = MagicMock()
        indicator.lookback_required = 20

        history = [(1.0, 2.0, 0.5, 1.5, 10.0, 1_700_000_000.0, 4.0)] * 20

        mock_fm = MagicMock()
        mock_fm.indicators = [indicator]
        mock_fm.fetch_historical_db_records = AsyncMock(return_value=history)
        mock_fm.get_unprimed_indicator_keys.return_value = []
        mock_fm.snapshot_features.return_value = dict(MOCK_FEATURE_RESULTS)
        MockFM.return_value = mock_fm

        worker = SignalWorker("BTCUSDT", "4h")
        worker.redis_client = AsyncMock()
        worker.redis_client.hgetall.return_value = {}
        worker.run = AsyncMock()

        await worker.start()

        assert worker.redis_client.xadd.call_count == 2
        calls = worker.redis_client.xadd.call_args_list
        assert calls[0][0][0] == "features:BTCUSDT:4h"
        assert calls[1][0][0] == "price_update:BTCUSDT:4h"
        worker.run.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("apps.signal_app.signal_worker.FeatureManager")
    async def test_start_raises_when_history_exists_but_indicators_never_prime(self, MockFM) -> None:
        """Enough history with persistent unprimed indicators should still fail fast."""
        from apps.signal_app.signal_worker import SignalWorker

        indicator = MagicMock()
        indicator.lookback_required = 20

        history = [(1.0, 2.0, 0.5, 1.5, 10.0, 1700000000.0)] * 20

        mock_fm = MagicMock()
        mock_fm.indicators = [indicator]
        mock_fm.fetch_historical_db_records = AsyncMock(return_value=history)
        mock_fm.get_unprimed_indicator_keys.return_value = ["RSI"]
        MockFM.return_value = mock_fm

        worker = SignalWorker("BTCUSDT", "4h")
        worker.run = AsyncMock()

        with pytest.raises(RuntimeError, match="Indicators failed to prime: RSI"):
            await worker.start()

        worker.run.assert_not_awaited()
