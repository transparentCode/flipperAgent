"""Tests for StrategyWorker — deserialization, idempotency key, signal conversion."""

from apps.strategy_app.settings import StrategyWorkerSettings
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

    def test_custom_worker_settings_applied(self):
        sw = StrategyWorker(
            "BTCUSDT",
            "1h",
            settings=StrategyWorkerSettings(
                consumer_group="custom_group",
                consumer_name_prefix="custom_worker",
                batch_size=25,
                block_ms=2500,
            ),
        )
        assert sw.group_name == "custom_group"
        assert sw.consumer_name == "custom_worker_BTCUSDT_1h"
        assert sw.batch_size == 25
        assert sw.block_ms == 2500
