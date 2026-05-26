"""Tests for SignalWorker.process_message()."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from libs.contracts.schemas import FeatureVector


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

        payload = _make_closed_bar_payload()
        await worker.process_message("msg-1", payload)

        mock_fm.process_tick.assert_called_once()
        worker.redis_client.xadd.assert_called_once()
        call_args = worker.redis_client.xadd.call_args
        assert call_args[0][0] == "features:BTCUSDT:4h"

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

        # Use seconds-based timestamp (< 1e12)
        payload = _make_closed_bar_payload(timestamp=1_700_000_000.0)
        await worker.process_message("msg-3", payload)

        # The data_tuple passed to process_tick should have the ms-converted timestamp
        call_args = mock_fm.process_tick.call_args[0][0]
        timestamp_in_tuple = call_args[5]
        assert timestamp_in_tuple == 1_700_000_000_000  # converted to ms
