"""Tests for StrategyWorker — deserialization, idempotency key, signal conversion."""

import json
import pytest

from apps.strategy_app.strategy_worker import StrategyWorker


class TestStrategyWorkerHelpers:
    def test_idempotency_key_deterministic(self):
        key1 = StrategyWorker._make_idempotency_key("MR", "BTC", "1h", 1000.0)
        key2 = StrategyWorker._make_idempotency_key("MR", "BTC", "1h", 1000.0)
        assert key1 == key2

    def test_idempotency_key_differs_on_timestamp(self):
        key1 = StrategyWorker._make_idempotency_key("MR", "BTC", "1h", 1000.0)
        key2 = StrategyWorker._make_idempotency_key("MR", "BTC", "1h", 2000.0)
        assert key1 != key2


class TestStrategyWorkerInit:
    def test_stream_keys(self):
        sw = StrategyWorker("BTCUSDT", "1h")
        assert sw.feature_stream_key == "features:BTCUSDT:1h"
        assert sw.signal_stream_key == "signals:BTCUSDT:1h"

    def test_model_manager_loaded(self):
        sw = StrategyWorker("BTCUSDT", "1h")
        assert len(sw.model_manager.models) >= 1
