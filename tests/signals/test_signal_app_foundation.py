from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import math
import pandas as pd
import pytest
from valkey.exceptions import TimeoutError as ValkeyTimeoutError

from apps.signal_app.feature_manager import FeatureManager
from apps.signal_app.api.dependencies import SignalApiDependencies
from apps.signal_app.catalog import SignalPairCatalog
from apps.signal_app.catalog.static import StaticSignalPairCatalog
from apps.signal_app.enrichment.valkey import ValkeySignalEnrichmentReader
from apps.signal_app.models import SignalPair, SignalPairState, SignalRuntimeStatus
from apps.signal_app.observability.status import SignalObservabilityService
from apps.signal_app.observability.runtime_state import runtime_status_key
from apps.signal_app.api.routes import signal_feature_snapshot, signal_latest, signal_status
from apps.signal_app.pipeline.engineered import EngineeredFeaturePipeline
from apps.signal_app.pipeline.features import FeaturePipeline
from apps.signal_app.pipeline.context_namespaces import (
    LTF_CONTEXT_PREFIX,
    TRANSPORT_CONTEXT_KEY,
    build_transport_context,
    ltf_context_key,
    merge_ltf_context,
)
from apps.signal_app.pipeline.priming import StartupPrimer, dataframe_to_bar_tuples
from apps.signal_app.pipeline.snapshot import _bar_tuple_to_candle as snapshot_bar_tuple_to_candle
from apps.signal_app.pipeline.raw_indicators import RawIndicatorPipeline
from apps.signal_app.pipeline.regime import FeatureProducerConfigResolver, RegimeFeaturePipeline
from apps.signal_app.pipeline.snapshot import FeatureSnapshotService
from apps.signal_app.publishing.streams import SignalStreamPublisher
from apps.signal_app.runtime.runner import SignalRuntimeRunner
from apps.signal_app.runtime.worker import SignalRuntimeWorker, _bar_tuple_to_candle as runtime_bar_tuple_to_candle
from apps.signal_app.settings import SignalWorkerSettings
from libs.common.config import ConfigManager
from libs.contracts.signal import FeatureVector, PriceUpdate, StreamOHLCVPayload
from libs.contracts.serialization import valkey_encode
from libs.features.engineered.manager import EngineeredFeatureManager
from apps.signal_app.models import SignalFeatureSnapshotRequest


def test_signal_pair_catalog_lists_configured_pairs() -> None:
    ConfigManager.reset_singleton()

    pairs = SignalPairCatalog().list_pairs()

    assert any(pair.asset == "BTCUSDT" and pair.timeframe == "1h" for pair in pairs)
    assert any(pair.asset == "ETHUSDT" and pair.timeframe == "4h" for pair in pairs)


def test_signal_pair_catalog_adds_runtime_base_pairs_and_context_profiles() -> None:
    catalog = SignalPairCatalog(config_manager=_signal_runtime_models_config_manager())

    pairs = {pair.key: pair for pair in catalog.list_pairs()}

    assert "BTCUSDT:1h" in pairs
    assert "BTCUSDT:1m" in pairs
    assert pairs["BTCUSDT:1h"].base_timeframe == "1m"
    assert pairs["BTCUSDT:1h"].required_context_profiles == ["volatility_60m"]
    assert pairs["BTCUSDT:1m"].required_context_profiles == ["volatility_60m"]


def test_feature_pipeline_builds_existing_contract_payloads() -> None:
    candle = StreamOHLCVPayload(
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp=1_700_000_000.0,
        open=100.0,
        high=110.0,
        low=95.0,
        close=105.0,
        volume=10.0,
        taker_buy_base=4.0,
        bar_closed=True,
    )

    feature_vector, price_update = FeaturePipeline().build_payloads(
        asset="BTCUSDT",
        timeframe="1h",
        candle=candle,
        features={"RSI": 55.0},
    )

    assert isinstance(feature_vector, FeatureVector)
    assert isinstance(price_update, PriceUpdate)
    assert feature_vector.timestamp == 1_700_000_000_000
    assert feature_vector.features["RSI"] == 55.0
    assert feature_vector.bar_data["taker_buy_base"] == 4.0
    assert price_update.close == 105.0


def test_runtime_bar_tuple_to_candle_adds_canonical_metadata() -> None:
    candle = runtime_bar_tuple_to_candle(
        "BTCUSDT",
        "1h",
        (100.0, 110.0, 95.0, 105.0, 10.0, 1_700_000_000.0, 4.0),
    )

    assert candle.base_timeframe == "1m"
    assert candle.bar_span_seconds == 3600
    assert candle.close_timestamp == 1_700_003_600.0
    assert candle.provider == "timescale"
    assert candle.origin == "bootstrap_snapshot"


def test_snapshot_bar_tuple_to_candle_adds_canonical_metadata() -> None:
    candle = snapshot_bar_tuple_to_candle(
        "BTCUSDT",
        "4h",
        (100.0, 110.0, 95.0, 105.0, 10.0, 1_700_000_000.0, 4.0),
    )

    assert candle.base_timeframe == "1m"
    assert candle.bar_span_seconds == 14_400
    assert candle.close_timestamp == 1_700_014_400.0
    assert candle.provider == "timescale"
    assert candle.origin == "timescale_snapshot"


def test_ltf_context_namespace_helpers_are_stable() -> None:
    assert ltf_context_key("volatility_60m") == f"{LTF_CONTEXT_PREFIX}_volatility_60m"

    merged = merge_ltf_context(
        {"RSI": 55.0},
        profiles={"volatility_60m": {"value": 1.2, "zscore": 0.8}},
    )

    assert merged["RSI"] == 55.0
    assert merged["ctx_ltf_volatility_60m"] == {"value": 1.2, "zscore": 0.8}

    candle = StreamOHLCVPayload(
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp=1_700_000_000.0,
        open=100.0,
        high=110.0,
        low=95.0,
        close=105.0,
        volume=10.0,
        bar_closed=True,
        base_timeframe="1m",
        bar_span_seconds=3600,
        close_timestamp=1_700_003_600.0,
        ingestion_timestamp=1_700_003_700_000.0,
        publication_lag_ms=100_000,
        provider="binance_native",
        origin="live_websocket",
    )
    assert build_transport_context(candle) == {
        "base_timeframe": "1m",
        "bar_span_seconds": 3600,
        "close_timestamp": 1_700_003_600.0,
        "ingestion_timestamp": 1_700_003_700_000.0,
        "publication_lag_ms": 100_000,
        "provider": "binance_native",
        "origin": "live_websocket",
    }


def test_feature_pipeline_merges_ltf_context_profiles() -> None:
    candle = StreamOHLCVPayload(
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp=1_700_000_000.0,
        open=100.0,
        high=110.0,
        low=95.0,
        close=105.0,
        volume=10.0,
        taker_buy_base=4.0,
        bar_closed=True,
    )

    features = FeaturePipeline().build_features(
        candle=candle,
        raw_features={"RSI": 55.0},
        ltf_context_profiles={"volatility_60m": {"value": 1.2}},
    )

    feature_vector, _ = FeaturePipeline().build_payloads(
        asset="BTCUSDT",
        timeframe="1h",
        candle=candle,
        features=features,
    )

    assert feature_vector.features["ctx_ltf_volatility_60m"] == {"value": 1.2}
    assert feature_vector.features[TRANSPORT_CONTEXT_KEY]["base_timeframe"] == "1m"
    assert feature_vector.features[TRANSPORT_CONTEXT_KEY]["bar_span_seconds"] == 60


def test_raw_indicator_pipeline_matches_current_feature_manager_for_live_tick() -> None:
    history = _history(length=260)
    tick = (126.0, 127.0, 125.0, 126.0, 1000.0, 1_700_000_000 + 261 * 3600, 560.0)

    ConfigManager.reset_singleton()
    current = FeatureManager("BTCUSDT", "1h")
    current.prime(history)
    current_result = current.process_tick(tick)

    ConfigManager.reset_singleton()
    v2 = RawIndicatorPipeline("BTCUSDT", "1h")
    v2.prime(history)
    v2_result = v2.process_tick(tick)

    _assert_feature_maps_close(v2_result, current_result)


def test_raw_indicator_pipeline_matches_current_feature_manager_for_snapshot() -> None:
    history = _history(length=260)

    ConfigManager.reset_singleton()
    current = FeatureManager("BTCUSDT", "1h")
    current.prime(history)
    current_snapshot = current.snapshot_features(history)

    ConfigManager.reset_singleton()
    v2 = RawIndicatorPipeline("BTCUSDT", "1h")
    v2.prime(history)
    v2_snapshot = v2.snapshot_features(history)

    _assert_feature_maps_close(v2_snapshot, current_snapshot)


def test_feature_pipeline_process_closed_candle_uses_raw_indicators() -> None:
    history = _history(length=260)
    ConfigManager.reset_singleton()
    raw = RawIndicatorPipeline("BTCUSDT", "1h")
    raw.prime(history)
    pipeline = FeaturePipeline(raw_indicators=raw)
    candle = StreamOHLCVPayload(
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp=1_700_000_000 + 261 * 3600,
        open=126.0,
        high=127.0,
        low=125.0,
        close=126.0,
        volume=1000.0,
        taker_buy_base=560.0,
        bar_closed=True,
    )

    feature_vector, price_update = pipeline.process_closed_candle(
        asset="BTCUSDT",
        timeframe="1h",
        candle=candle,
    )

    assert feature_vector.asset == "BTCUSDT"
    assert feature_vector.timeframe == "1h"
    assert "RSI" in feature_vector.features
    assert "MACD" in feature_vector.features
    assert price_update.close == 126.0


def test_raw_indicator_pipeline_expected_short_history_logs_warning_not_error() -> None:
    history = _history(length=5)

    ConfigManager.reset_singleton()
    with patch("apps.signal_app.pipeline.raw_indicators.logger") as mock_logger:
        raw = RawIndicatorPipeline("BTCUSDT", "1h")
        raw.prime(history)

    assert raw.get_unprimed_indicator_keys()
    assert mock_logger.warning.called
    mock_logger.error.assert_not_called()


def test_engineered_pipeline_matches_shared_manager() -> None:
    raw_features = {
        "Momentum": 4.0,
        "RSI": 60.0,
        "ATR": 2.0,
        "BollingerBands": (100.0, 110.0, 90.0),
        "KeltnerChannel": (100.0, 108.0, 92.0),
        "ADX": {"adx": 35.0, "plus_di": 30.0, "minus_di": 20.0},
        "KAMA_slow": 100.0,
    }
    bar_data = {
        "open": 100.0,
        "high": 110.0,
        "low": 95.0,
        "close": 105.0,
        "volume": 1000.0,
        "taker_buy_base": 560.0,
    }
    index_data = {
        "BTC.D": {"close": 53.0, "high": 54.0, "low": 52.0},
        "TOTAL2": {"close": 2_000.0, "high": 2_020.0, "low": 1_980.0},
        "TOTAL3": {"close": 1_000.0, "high": 1_010.0, "low": 990.0},
    }

    ConfigManager.reset_singleton()
    expected = EngineeredFeatureManager("BTCUSDT", "1h").compute(
        raw_features,
        bar_data,
        index_data=index_data,
    )

    ConfigManager.reset_singleton()
    actual = EngineeredFeaturePipeline("BTCUSDT", "1h").compute(
        raw_features,
        bar_data,
        index_data=index_data,
    )

    _assert_feature_maps_close(actual, expected)
    assert "eng_regime_score" in actual
    assert "eng_btc_dominance_regime" in actual


def test_feature_pipeline_adds_engineered_and_derivatives_features() -> None:
    candle = StreamOHLCVPayload(
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp=1_700_000_000.0,
        open=100.0,
        high=110.0,
        low=95.0,
        close=105.0,
        volume=1000.0,
        taker_buy_base=560.0,
        bar_closed=True,
    )
    raw_features = {
        "Momentum": 4.0,
        "RSI": 60.0,
        "ATR": 2.0,
        "BollingerBands": (100.0, 110.0, 90.0),
        "KeltnerChannel": (100.0, 108.0, 92.0),
        "ADX": {"adx": 35.0, "plus_di": 30.0, "minus_di": 20.0},
        "KAMA_slow": 100.0,
    }

    ConfigManager.reset_singleton()
    pipeline = FeaturePipeline(
        engineered_features=EngineeredFeaturePipeline("BTCUSDT", "1h"),
    )
    features = pipeline.build_features(
        candle=candle,
        raw_features=raw_features,
        index_data={"BTC.D": {"close": 53.0}},
        derivatives_data={"BTCUSDT_open_interest": 99.5},
    )

    assert features["Momentum"] == 4.0
    assert "eng_regime_score" in features
    assert features["BTCUSDT_open_interest"] == 99.5


def test_feature_producer_config_resolver_deep_merges_fallbacks(monkeypatch) -> None:
    ConfigManager.reset_singleton()
    config_manager = ConfigManager()
    monkeypatch.setattr(config_manager, "_load_configs", lambda trigger_callbacks=True: None)
    monkeypatch.setattr(ConfigManager, "register_file", lambda self, _: None)
    config_manager._state = {
        "feature_producers": {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "RegimeClassification": {
                                "enabled": False,
                                "params": {"hurst_lookback": 100, "hmm_student_df": 5.0},
                            }
                        },
                        "1h": {
                            "RegimeClassification": {
                                "params": {"hmm_student_df": 7.0},
                            }
                        },
                    }
                },
                "BTCUSDT": {
                    "timeframes": {
                        "default": {
                            "RegimeClassification": {
                                "enabled": True,
                                "frozen_overrides": {"hmm_n_states": 3},
                            }
                        },
                        "1h": {
                            "RegimeClassification": {
                                "params": {"hurst_lookback": 120},
                            }
                        },
                    }
                },
            }
        }
    }

    resolved = FeatureProducerConfigResolver(config_manager).resolve(
        "BTCUSDT",
        "1h",
        "RegimeClassification",
    )

    assert resolved == {
        "enabled": True,
        "params": {"hurst_lookback": 120, "hmm_student_df": 7.0},
        "frozen_overrides": {"hmm_n_states": 3},
    }


@pytest.mark.asyncio
async def test_regime_pipeline_attaches_snapshot_classification_and_l2() -> None:
    class FakeOrchestrator:
        def analyze(self, frame: pd.DataFrame):
            assert len(frame) >= 3
            return SimpleNamespace(
                regime="CLEAN_TREND_BULL",
                p_trending=0.8,
                vol_percentile=65.0,
                changepoint_prob=0.2,
                adaptive_period=24,
                position_scale=1.1,
                atr_multiplier=2.0,
                holding_period=12,
                hilbert_period=28.0,
                hilbert_confidence=0.7,
            )

    class FakeClassifier:
        def __init__(self) -> None:
            self.calls = 0

        def batch_evaluate(self, frame: pd.DataFrame) -> pd.DataFrame:
            self.calls += 1
            assert len(frame) >= 3
            return pd.DataFrame([{"condition_scale": 0.42, "hurst": 0.55}])

    async def load_l2(asset: str) -> dict[str, float]:
        assert asset == "BTCUSDT"
        return {"spread_bps": 1.5}

    classifier = FakeClassifier()
    regime = RegimeFeaturePipeline(
        "BTCUSDT",
        "1h",
        min_bars=3,
        reeval_interval=10,
        orchestrator=FakeOrchestrator(),
        classifier=classifier,
        l2_reader=load_l2,
    )
    regime.prime(_history(length=3))

    enriched = await regime.enrich({"RSI": 55.0})
    regime.append_bar(
        {
            "open": 101.0,
            "high": 102.0,
            "low": 100.0,
            "close": 101.0,
            "volume": 1000.0,
            "taker_buy_base": 560.0,
        }
    )
    enriched_cached = await regime.enrich({"RSI": 56.0})

    assert enriched["regime_snapshot"]["regime"] == "CLEAN_TREND_BULL"
    assert enriched["regime_classification"]["condition_scale"] == 0.42
    assert enriched["regime_classification"]["spread_bps"] == 1.5
    assert enriched_cached["regime_classification"]["_regime_staleness_bars"] == 1
    assert classifier.calls == 1


@pytest.mark.asyncio
async def test_signal_stream_publisher_uses_current_stream_contracts() -> None:
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(return_value="1-0")
    publisher = SignalStreamPublisher(redis_client)

    await publisher.publish_feature_vector(
        FeatureVector(
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1_700_000_000_000,
            features={"RSI": 55.0},
            bar_data={"close": 105.0},
        )
    )
    await publisher.publish_price_update(
        PriceUpdate(
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1_700_000_000_000,
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            volume=10.0,
        )
    )

    assert redis_client.xadd.await_args_list[0].args[0] == "features:BTCUSDT:1h"
    assert redis_client.xadd.await_args_list[1].args[0] == "price_update:BTCUSDT:1h"
    assert redis_client.xadd.await_args_list[0].kwargs["maxlen"] == 5000
    assert redis_client.xadd.await_args_list[1].kwargs["maxlen"] == 500


@pytest.mark.asyncio
async def test_signal_stream_publisher_supports_projected_trigger_lane_streams() -> None:
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(return_value="1-0")
    publisher = SignalStreamPublisher(redis_client)

    await publisher.publish_feature_vector(
        FeatureVector(
            asset="BTCUSDT",
            timeframe="4h",
            timestamp=1_700_000_000_000,
            features={"RSI": 55.0},
            bar_data={"close": 105.0},
        ),
        trigger_timeframe="1m",
    )

    assert redis_client.xadd.await_args_list[0].args[0] == "features:BTCUSDT:4h@1m"


@pytest.mark.asyncio
async def test_signal_runtime_worker_processes_closed_bar() -> None:
    class StubPipeline:
        enrichment_reader = None

        def __init__(self) -> None:
            self.calls = []

        async def process_closed_candle_enriched(self, *, asset, timeframe, candle):
            self.calls.append((asset, timeframe, candle))
            return (
                FeatureVector(
                    asset=asset,
                    timeframe=timeframe,
                    timestamp=1_700_000_000_000,
                    features={"RSI": 55.0},
                    bar_data={"close": candle.close},
                ),
                PriceUpdate(
                    asset=asset,
                    timeframe=timeframe,
                    timestamp=1_700_000_000_000,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                ),
            )

    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(return_value="1-0")
    pipeline = StubPipeline()
    worker = SignalRuntimeWorker("BTCUSDT", "1h", pipeline=pipeline)
    worker.redis_client = redis_client

    await worker.process_message(
        "1-0",
        {
            b"bar_closed": b"true",
            b"symbol": b"BTCUSDT",
            b"timeframe": b"1h",
            b"timestamp": b"1700000000",
            b"open": b"100.0",
            b"high": b"110.0",
            b"low": b"95.0",
            b"close": b"105.0",
            b"volume": b"10.0",
            b"taker_buy_base": b"4.0",
        },
    )

    assert len(pipeline.calls) == 1
    assert pipeline.calls[0][2].timestamp == 1_700_000_000.0
    assert redis_client.xadd.await_args_list[0].args[0] == "features:BTCUSDT:1h"
    assert redis_client.xadd.await_args_list[1].args[0] == "price_update:BTCUSDT:1h"


@pytest.mark.asyncio
async def test_signal_runtime_worker_projects_decision_view_on_base_trigger_lane() -> None:
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(return_value="1-0")
    redis_client.hset = AsyncMock(return_value=1)
    redis_client.hgetall = AsyncMock(return_value={})
    raw = _FakeRawIndicators(snapshot={"RSI": 55.0}, live={"RSI": 56.0})
    pipeline = FeaturePipeline(raw_indicators=raw)
    worker = SignalRuntimeWorker(
        "BTCUSDT",
        "4h",
        pipeline=pipeline,
        trigger_timeframe="1m",
        trigger_mode="on_base_bar_close",
        required_context_profiles=["volatility_15m"],
    )
    await worker.connect(redis_client)
    history_4h = _history(length=8)
    history_1m = _history_1m(length=240)
    worker._prime_projection_history(history_4h)
    worker._prime_source_history(history_1m)
    worker._prime_ltf_history(history_1m)

    await worker.process_message(
        "1-0",
        {
            b"bar_closed": b"true",
            b"symbol": b"BTCUSDT",
            b"timeframe": b"1m",
            b"timestamp": str(int(history_1m[-1][5] + 60)).encode(),
            b"open": b"100.0",
            b"high": b"101.0",
            b"low": b"99.0",
            b"close": b"100.5",
            b"volume": b"10.0",
            b"taker_buy_base": b"4.0",
        },
    )

    assert redis_client.xadd.await_args_list[0].args[0] == "features:BTCUSDT:4h@1m"
    payload = redis_client.xadd.await_args_list[0].args[1]
    assert payload["timeframe"] == "4h"


@pytest.mark.asyncio
async def test_signal_runtime_worker_base_lane_publishes_ltf_context_profiles() -> None:
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(return_value="1-0")
    redis_client.hset = AsyncMock(return_value=1)
    redis_client.expire = AsyncMock(return_value=True)
    redis_client.hgetall = AsyncMock(return_value={})

    class StubPipeline:
        enrichment_reader = None

        def __init__(self) -> None:
            self.calls = []

        async def process_closed_candle_enriched(
            self,
            *,
            asset,
            timeframe,
            candle,
            ltf_context_profiles=None,
        ):
            self.calls.append(ltf_context_profiles or {})
            return (
                FeatureVector(
                    asset=asset,
                    timeframe=timeframe,
                    timestamp=1_700_000_000_000,
                    features={"RSI": 55.0},
                    bar_data={"close": candle.close},
                ),
                PriceUpdate(
                    asset=asset,
                    timeframe=timeframe,
                    timestamp=1_700_000_000_000,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                ),
            )

    pipeline = StubPipeline()
    worker = SignalRuntimeWorker(
        "BTCUSDT",
        "1m",
        pipeline=pipeline,
        required_context_profiles=["volatility_15m"],
    )
    await worker.connect(redis_client)
    worker._prime_ltf_history(_history_1m(length=15))

    await worker.process_message(
        "1-0",
        {
            b"bar_closed": b"true",
            b"symbol": b"BTCUSDT",
            b"timeframe": b"1m",
            b"timestamp": b"1700000900",
            b"open": b"100.0",
            b"high": b"101.0",
            b"low": b"99.0",
            b"close": b"100.5",
            b"volume": b"10.0",
            b"taker_buy_base": b"4.0",
        },
    )

    assert any(
        call.args[0] == "signal:ltf_context:BTCUSDT:1m:volatility_15m"
        for call in redis_client.hset.await_args_list
    )
    assert any(
        call.args[0] == "signal:ltf_context:BTCUSDT:1m:volatility_15m" and call.args[1] == 21_600
        for call in redis_client.expire.await_args_list
    )
    assert "volatility_15m" in pipeline.calls[0]
    assert "value" in pipeline.calls[0]["volatility_15m"]


@pytest.mark.asyncio
async def test_signal_runtime_worker_ignores_open_and_invalid_bars() -> None:
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(return_value="1-0")
    pipeline = AsyncMock()
    pipeline.enrichment_reader = None
    worker = SignalRuntimeWorker("BTCUSDT", "1h", pipeline=pipeline)
    worker.redis_client = redis_client

    await worker.process_message("1-0", {"bar_closed": "false"})
    await worker.process_message("1-1", {"bar_closed": "true", "close": "bad"})

    pipeline.process_closed_candle_enriched.assert_not_called()
    redis_client.xadd.assert_not_called()


@pytest.mark.asyncio
async def test_signal_runtime_worker_publish_failure_bubbles() -> None:
    class StubPipeline:
        enrichment_reader = None

        async def process_closed_candle_enriched(self, *, asset, timeframe, candle):
            return (
                FeatureVector(asset=asset, timeframe=timeframe, timestamp=1.0, features={}, bar_data={}),
                PriceUpdate(
                    asset=asset,
                    timeframe=timeframe,
                    timestamp=1.0,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                ),
            )

    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(side_effect=RuntimeError("stream publish failed"))
    worker = SignalRuntimeWorker("BTCUSDT", "1h", pipeline=StubPipeline())
    worker.redis_client = redis_client

    with pytest.raises(RuntimeError, match="stream publish failed"):
        await worker.process_message(
            "1-0",
            {
                "bar_closed": "true",
                "timestamp": "1700000000",
                "open": "100.0",
                "high": "110.0",
                "low": "95.0",
                "close": "105.0",
                "volume": "10.0",
            },
        )


def test_dataframe_to_bar_tuples_normalizes_timestamp_and_nan_taker_buy() -> None:
    frame = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-01-01T00:00:00Z"),
                "open": 100.0,
                "high": 110.0,
                "low": 95.0,
                "close": 105.0,
                "volume": 10.0,
                "taker_buy_base": math.nan,
            }
        ]
    )

    rows = dataframe_to_bar_tuples(frame)

    assert rows == [(100.0, 110.0, 95.0, 105.0, 10.0, 1_767_225_600.0, 0.0)]


@pytest.mark.asyncio
async def test_signal_runtime_worker_primes_startup_history() -> None:
    raw = _FakeRawIndicators(snapshot={"RSI": 55.0})
    pipeline = FeaturePipeline(raw_indicators=raw)
    primer = StartupPrimer(AsyncMock(return_value=_history(length=4)))
    worker = SignalRuntimeWorker(
        "BTCUSDT",
        "1h",
        pipeline=pipeline,
        primer=primer,
    )

    history = await worker.prime_startup_history(4)

    assert history == _history(length=4)
    assert raw.prime_calls == [_history(length=4)]


def test_signal_runtime_worker_applies_settings_defaults() -> None:
    settings = SignalWorkerSettings(
        consumer_group="signal_test_group",
        consumer_name_prefix="signal_test_worker",
        batch_size=25,
        block_ms=2500,
        priming_retry_delay_sec=2.5,
        warming_retry_delay_sec=7.5,
        enrichment_index_keys=("TOTAL3ES",),
        regime_min_bars=300,
        regime_max_history=4000,
        regime_reeval_interval=12,
    )

    worker = SignalRuntimeWorker("BTCUSDT", "1h", settings=settings)

    assert worker.group_name == "signal_test_group"
    assert worker.consumer_name == "signal_test_worker_BTCUSDT_1h"
    assert worker.batch_size == 25
    assert worker.block_ms == 2500
    assert worker.startup_retry_delay_sec == 7.5
    assert worker.settings.priming_retry_delay_sec == 2.5
    assert worker.settings.enrichment_index_keys == ("TOTAL3ES",)
    assert worker.pipeline.regime_features is not None
    assert worker.pipeline.regime_features.min_bars == 300
    assert worker.pipeline.regime_features.max_history == 4000
    assert worker.pipeline.regime_features.reeval_interval == 12


def test_signal_worker_settings_from_config_reads_runtime_and_regime_overrides(monkeypatch) -> None:
    ConfigManager.reset_singleton()
    config_manager = ConfigManager()
    monkeypatch.setattr(config_manager, "_load_configs", lambda trigger_callbacks=True: None)
    monkeypatch.setattr(ConfigManager, "register_file", lambda self, _: None)
    config_manager._state = {
        "signal": {
            "runtime": {
                "consumer_group": "signal_cfg_group",
                "consumer_name_prefix": "signal_cfg_worker",
                "batch_size": 42,
                "block_ms": 2100,
                "priming_retry_delay_sec": 3.0,
                "warming_retry_delay_sec": 9.0,
            },
            "regime": {
                "min_bars": 333,
                "max_history": 4444,
                "reeval_interval": 6,
            },
        },
        "tradingview": {
            "indices": ["CRYPTOCAP:TOTAL3ES"],
        },
    }

    settings = SignalWorkerSettings.from_config(config_manager)

    assert settings.consumer_group == "signal_cfg_group"
    assert settings.consumer_name_prefix == "signal_cfg_worker"
    assert settings.batch_size == 42
    assert settings.block_ms == 2100
    assert settings.priming_retry_delay_sec == 3.0
    assert settings.warming_retry_delay_sec == 9.0
    assert settings.enrichment_index_keys == ("TOTAL3ES",)
    assert settings.regime_min_bars == 333
    assert settings.regime_max_history == 4444
    assert settings.regime_reeval_interval == 6


@pytest.mark.asyncio
async def test_signal_runtime_worker_bootstrap_snapshot_publishes_without_live_tick() -> None:
    raw = _FakeRawIndicators(snapshot={"RSI": 55.0})
    pipeline = FeaturePipeline(raw_indicators=raw)
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(return_value="1-0")
    worker = SignalRuntimeWorker("BTCUSDT", "1h", pipeline=pipeline)
    worker.redis_client = redis_client

    await worker.publish_bootstrap_snapshot(_history(length=4))

    assert raw.process_tick_calls == []
    assert redis_client.xadd.await_args_list[0].args[0] == "features:BTCUSDT:1h"
    assert redis_client.xadd.await_args_list[1].args[0] == "price_update:BTCUSDT:1h"
    assert worker._last_processed_ts == 1_700_010_800_000


@pytest.mark.asyncio
async def test_signal_runtime_worker_gap_reprime_before_processing() -> None:
    raw = _FakeRawIndicators(snapshot={"RSI": 55.0}, live={"RSI": 56.0})

    class StubPipeline(FeaturePipeline):
        async def process_closed_candle_enriched(self, *, asset, timeframe, candle):
            raw.process_tick(
                (
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.volume,
                    candle.timestamp,
                )
            )
            return (
                FeatureVector(
                    asset=asset,
                    timeframe=timeframe,
                    timestamp=1_700_021_600_000,
                    features={"RSI": 56.0},
                    bar_data={"close": candle.close},
                ),
                PriceUpdate(
                    asset=asset,
                    timeframe=timeframe,
                    timestamp=1_700_021_600_000,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                ),
            )

    pipeline = StubPipeline(raw_indicators=raw)
    primer = StartupPrimer(AsyncMock(return_value=_history(length=5)))
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(return_value="1-0")
    worker = SignalRuntimeWorker(
        "BTCUSDT",
        "1h",
        pipeline=pipeline,
        primer=primer,
    )
    worker.redis_client = redis_client
    worker._last_processed_ts = 1_700_000_000_000

    await worker.process_message(
        "1-0",
        {
            "bar_closed": "true",
            "timestamp": "1700021600",
            "open": "100.0",
            "high": "110.0",
            "low": "95.0",
            "close": "105.0",
            "volume": "10.0",
        },
    )

    assert raw.prime_calls == [_history(length=5)]
    assert len(raw.process_tick_calls) == 1
    assert redis_client.xadd.await_count == 2


@pytest.mark.asyncio
async def test_signal_runtime_worker_gap_reprime_degrades_on_partial_history() -> None:
    raw = _FakeRawIndicators(
        snapshot={"RSI": 55.0},
        live={"RSI": 56.0},
        unprimed=["MACD", "ATR"],
    )
    raw.indicators = [SimpleNamespace(lookback_required=10)]

    class StubPipeline(FeaturePipeline):
        async def process_closed_candle_enriched(self, *, asset, timeframe, candle):
            raw.process_tick(
                (
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.volume,
                    candle.timestamp,
                )
            )
            return (
                FeatureVector(
                    asset=asset,
                    timeframe=timeframe,
                    timestamp=1_700_021_600_000,
                    features={"RSI": 56.0},
                    bar_data={"close": candle.close},
                ),
                PriceUpdate(
                    asset=asset,
                    timeframe=timeframe,
                    timestamp=1_700_021_600_000,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                ),
            )

    pipeline = StubPipeline(raw_indicators=raw)
    primer = StartupPrimer(AsyncMock(return_value=_history(length=5)))
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(return_value="1-0")
    worker = SignalRuntimeWorker(
        "BTCUSDT",
        "1h",
        pipeline=pipeline,
        primer=primer,
    )
    worker.redis_client = redis_client
    worker.state_store = AsyncMock()
    worker._last_processed_ts = 1_700_000_000_000

    await worker.process_message(
        "1-0",
        {
            "bar_closed": "true",
            "timestamp": "1700021600",
            "open": "100.0",
            "high": "110.0",
            "low": "95.0",
            "close": "105.0",
            "volume": "10.0",
        },
    )

    assert raw.prime_calls == [_history(length=5)]
    assert len(raw.process_tick_calls) == 1
    assert redis_client.xadd.await_count == 2
    worker.state_store.update.assert_any_await(
        SignalPair(asset="BTCUSDT", timeframe="1h"),
        state=SignalPairState.DEGRADED,
        last_input_ts=1_700_021_600.0,
        last_feature_ts=1_700_021_600_000.0,
        last_error=None,
        replace_last_error=True,
        detail={"phase": "live"},
    )


@pytest.mark.asyncio
async def test_signal_runtime_runner_connects_and_stops_workers() -> None:
    class StubWorker:
        def __init__(self, asset: str, timeframe: str) -> None:
            self.asset = asset
            self.timeframe = timeframe
            self.connected = False
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def connect(self, redis_client) -> None:
            self.connected = redis_client is not None

        async def start(self) -> None:
            self.started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    catalog = SignalPairCatalog(config_manager=_signal_models_config_manager())
    runner = SignalRuntimeRunner(catalog=catalog, worker_factory=StubWorker)

    redis_client = AsyncMock()
    redis_client.xgroup_create = AsyncMock()
    redis_client.xreadgroup = AsyncMock(side_effect=asyncio.CancelledError())

    workers = await runner.connect(redis_client=redis_client)
    assert workers
    assert all(worker.connected for worker in workers)

    start_task = asyncio.create_task(runner.start())
    await asyncio.gather(*(worker.started.wait() for worker in workers))
    await runner.stop()
    await start_task

    assert all(worker.cancelled.is_set() for worker in workers)


@pytest.mark.asyncio
async def test_signal_runtime_runner_lifecycle_watcher_retries_timeout() -> None:
    runner = SignalRuntimeRunner(catalog=StaticSignalPairCatalog([]))
    runner.redis_client = AsyncMock()
    runner.worker_settings = SignalWorkerSettings(block_ms=1)
    runner.redis_client.xreadgroup = AsyncMock(
        side_effect=[
            ValkeyTimeoutError("Timeout reading from broker:6379"),
            [("asset:lifecycle", [("1-0", {"event_id": "evt-1"})])],
            asyncio.CancelledError(),
        ]
    )
    runner.redis_client.xack = AsyncMock()
    runner._apply_lifecycle_event = AsyncMock()

    event = SimpleNamespace(
        event_id="evt-1",
        symbol="SOLUSDT",
        base_timeframe="1m",
        publish_timeframes=["1m"],
        desired_state="REMOVING",
        enabled=False,
        reason="cleanup",
    )

    with (
        patch("apps.signal_app.runtime.runner.valkey_decode", return_value=event),
        patch("apps.signal_app.runtime.runner.mark_lifecycle_event_processed", new=AsyncMock(return_value=True)),
        pytest.raises(asyncio.CancelledError),
    ):
        await runner._watch_lifecycle()

    runner._apply_lifecycle_event.assert_awaited_once_with(event)
    runner.redis_client.xack.assert_awaited_once()


def test_signal_runtime_runner_passes_worker_settings_when_supported() -> None:
    seen_settings: list[SignalWorkerSettings] = []

    class StubWorker:
        def __init__(self, asset: str, timeframe: str, *, settings: SignalWorkerSettings) -> None:
            self.asset = asset
            self.timeframe = timeframe
            seen_settings.append(settings)

    catalog = SignalPairCatalog(config_manager=_signal_models_config_manager())
    settings = SignalWorkerSettings(consumer_group="custom_group")
    runner = SignalRuntimeRunner(
        catalog=catalog,
        worker_factory=StubWorker,
        worker_settings=settings,
    )

    workers = runner.build_workers()

    assert workers
    assert seen_settings
    assert all(item.consumer_group == "custom_group" for item in seen_settings)


@pytest.mark.asyncio
async def test_feature_snapshot_service_computes_from_inline_bars() -> None:
    ConfigManager.reset_singleton()
    feature_vector = await FeatureSnapshotService().compute(
        asset="BTCUSDT",
        timeframe="1h",
        lookback=260,
        bars=_history_bars(length=260),
    )

    assert feature_vector.asset == "BTCUSDT"
    assert feature_vector.timeframe == "1h"
    assert "RSI" in feature_vector.features
    assert "eng_regime_score" in feature_vector.features


@pytest.mark.asyncio
async def test_signal_feature_snapshot_route_returns_feature_vector() -> None:
    ConfigManager.reset_singleton()
    result = await signal_feature_snapshot(
        SignalFeatureSnapshotRequest(
            asset="btcusdt",
            timeframe="1h",
            lookback=260,
            bars=_history_bars(length=260),
        )
    )

    assert result["status"] == "ok"
    assert result["feature_vector"]["asset"] == "BTCUSDT"
    assert "RSI" in result["feature_vector"]["features"]


@pytest.mark.asyncio
async def test_signal_latest_route_returns_latest_feature(monkeypatch) -> None:
    redis_client = AsyncMock()
    redis_client.xrevrange.return_value = [
        (
            "1-0",
            {
                "timestamp": "1700000000000",
                "features": '{"RSI": 55.0}',
                "bar_data": '{"close": 105.0}',
            },
        )
    ]
    redis_client.aclose = AsyncMock()

    deps = SignalApiDependencies(config_manager=_signal_models_config_manager())
    deps.open_observability = AsyncMock(
        return_value=(
            SignalObservabilityService(redis_client, deps.catalog()),
            redis_client,
        )
    )
    monkeypatch.setattr("apps.signal_app.api.routes.get_signal_api_dependencies", lambda: deps)

    latest = await signal_latest()

    assert latest["BTCUSDT:1h"]["status"] == "ok"
    assert latest["BTCUSDT:1h"]["features"]["RSI"] == 55.0
    redis_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_signal_status_route_returns_runtime_status(monkeypatch) -> None:
    redis_client = AsyncMock()
    redis_client.xrevrange.return_value = [
        (
            "1-0",
            {
                "timestamp": "1700000000000",
                "features": '{"RSI": 55.0}',
                "bar_data": '{"close": 105.0}',
            },
        )
    ]
    redis_client.hgetall.return_value = {}
    redis_client.aclose = AsyncMock()

    deps = SignalApiDependencies(config_manager=_signal_models_config_manager())
    deps.open_observability = AsyncMock(
        return_value=(
            SignalObservabilityService(redis_client, deps.catalog()),
            redis_client,
        )
    )
    monkeypatch.setattr("apps.signal_app.api.routes.get_signal_api_dependencies", lambda: deps)

    status = await signal_status()

    assert status["BTCUSDT:1h"].pair.asset == "BTCUSDT"
    assert status["BTCUSDT:1h"].last_feature_ts == 1_700_000_000_000.0
    assert status["BTCUSDT:1h"].detail["latest_status"] == "ok"
    redis_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_valkey_enrichment_reader_decodes_index_and_derivatives(monkeypatch) -> None:
    ConfigManager.reset_singleton()
    config_manager = ConfigManager()
    monkeypatch.setattr(config_manager, "_load_configs", lambda trigger_callbacks=True: None)
    monkeypatch.setattr(ConfigManager, "register_file", lambda self, _: None)
    config_manager._state = {
        "tradingview": {
            "indices": ["CRYPTOCAP:TOTAL3ES"],
            "derivatives": [
                {"asset": "BTCUSDT", "data_type": "open_interest"},
            ],
        }
    }

    redis_client = AsyncMock()

    async def hgetall(key: str):
        if key == "index:latest:TOTAL3ES":
            return {"symbol": "TOTAL3ES", "close": "123.4", "timestamp": "1700000000000"}
        if key == "derivatives:latest:BTCUSDT:oi":
            return {"value": "99.5"}
        return {}

    redis_client.hgetall.side_effect = hgetall
    reader = ValkeySignalEnrichmentReader(redis_client, config_manager=config_manager)

    index_data = await reader.load_index_data()
    derivatives = await reader.load_derivatives_data()

    assert index_data["TOTAL3ES"]["close"] == 123.4
    assert derivatives["BTCUSDT_open_interest"] == 99.5


@pytest.mark.asyncio
async def test_valkey_enrichment_reader_decodes_ltf_context_profiles(monkeypatch) -> None:
    ConfigManager.reset_singleton()
    config_manager = ConfigManager()
    monkeypatch.setattr(config_manager, "_load_configs", lambda trigger_callbacks=True: None)
    monkeypatch.setattr(ConfigManager, "register_file", lambda self, _: None)
    config_manager._state = {"tradingview": {"indices": []}}

    redis_client = AsyncMock()
    redis_client.hgetall.return_value = {
        "value": "0.0123",
        "window_bars": "60",
        "base_timeframe": "1m",
    }
    reader = ValkeySignalEnrichmentReader(redis_client, config_manager=config_manager)

    profiles = await reader.load_ltf_context_profiles(
        asset="BTCUSDT",
        base_timeframe="1m",
        profiles=["volatility_60m"],
    )

    assert profiles["volatility_60m"]["value"] == 0.0123
    assert profiles["volatility_60m"]["window_bars"] == 60.0


@pytest.mark.asyncio
async def test_signal_observability_service_reads_latest_feature(monkeypatch) -> None:
    ConfigManager.reset_singleton()
    config_manager = ConfigManager()
    monkeypatch.setattr(config_manager, "_load_configs", lambda trigger_callbacks=True: None)
    monkeypatch.setattr(ConfigManager, "register_file", lambda self, _: None)
    config_manager._state = {
        "models": {
            "assets": {
                "BTCUSDT": {"timeframes": {"1h": {"MeanReversion": {"enabled": True}}}},
            }
        }
    }

    redis_client = AsyncMock()
    redis_client.xrevrange.return_value = [
        (
            "1-0",
            {
                "timestamp": "1700000000000",
                "features": '{"RSI": 55.0}',
                "bar_data": '{"close": 105.0}',
            },
        )
    ]
    redis_client.hgetall.return_value = {}

    service = SignalObservabilityService(
        redis_client,
        SignalPairCatalog(config_manager=config_manager),
    )

    latest = await service.latest_features()

    assert latest["BTCUSDT:1h"]["status"] == "ok"
    assert latest["BTCUSDT:1h"]["features"]["RSI"] == 55.0


@pytest.mark.asyncio
async def test_signal_observability_service_reads_persisted_runtime_state(monkeypatch) -> None:
    ConfigManager.reset_singleton()
    config_manager = ConfigManager()
    monkeypatch.setattr(config_manager, "_load_configs", lambda trigger_callbacks=True: None)
    monkeypatch.setattr(ConfigManager, "register_file", lambda self, _: None)
    config_manager._state = {
        "models": {
            "assets": {
                "BTCUSDT": {"timeframes": {"1h": {"MeanReversion": {"enabled": True}}}},
            }
        }
    }

    persisted = SignalRuntimeStatus(
        pair=SignalPair(asset="BTCUSDT", timeframe="1h"),
        state=SignalPairState.DEGRADED,
        last_input_ts=1_700_000_100_000.0,
        last_feature_ts=1_700_000_200_000.0,
        last_error="bootstrap degraded",
        detail={"phase": "bootstrap"},
    )

    redis_client = AsyncMock()
    redis_client.xrevrange.return_value = [
        (
            "1-0",
            {
                "timestamp": "1700000300000",
                "features": '{"RSI": 55.0}',
                "bar_data": '{"close": 105.0}',
            },
        )
    ]

    async def hgetall(key: str):
        if key == runtime_status_key("BTCUSDT", "1h"):
            return valkey_encode(persisted, inject_trace=False)
        return {}

    redis_client.hgetall.side_effect = hgetall

    service = SignalObservabilityService(
        redis_client,
        SignalPairCatalog(config_manager=config_manager),
    )

    status = await service.status()

    assert status["BTCUSDT:1h"].state == SignalPairState.DEGRADED
    assert status["BTCUSDT:1h"].last_error == "bootstrap degraded"
    assert status["BTCUSDT:1h"].last_feature_ts == 1_700_000_200_000.0
    assert status["BTCUSDT:1h"].detail["phase"] == "bootstrap"
    assert status["BTCUSDT:1h"].detail["latest_status"] == "ok"


def _signal_models_config_manager() -> ConfigManager:
    ConfigManager.reset_singleton()
    config_manager = ConfigManager()
    config_manager._state = {
        "models": {
            "assets": {
                "BTCUSDT": {"timeframes": {"1h": {"MeanReversion": {"enabled": True}}}},
                "ETHUSDT": {"timeframes": {"4h": {"TrendFollowing": {"enabled": True}}}},
            }
        }
    }
    return config_manager


def _signal_runtime_models_config_manager() -> ConfigManager:
    ConfigManager.reset_singleton()
    config_manager = ConfigManager()
    config_manager.register_file = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    config_manager._load_configs = lambda trigger_callbacks=True: None  # type: ignore[method-assign]
    config_manager._state = {
        "models": {
            "assets": {
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "Momentum": {
                                "enabled": True,
                                "runtime": {
                                    "decision_timeframe": "1h",
                                    "base_timeframe": "1m",
                                    "required_context_profiles": ["volatility_60m"],
                                },
                            }
                        }
                    }
                }
            }
        }
    }
    return config_manager


def _history(length: int) -> list[tuple[float, ...]]:
    base_ts = 1_700_000_000
    rows = []
    for index in range(length):
        close = 100.0 + index * 0.1
        rows.append(
            (
                close,
                close + 1,
                close - 1,
                close,
                1000.0,
                base_ts + index * 3600,
                550.0 + (index % 20),
            )
        )
    return rows


def _history_1m(length: int) -> list[tuple[float, ...]]:
    base_ts = 1_700_000_000
    rows = []
    for index in range(length):
        close = 100.0 + index * 0.01
        rows.append(
            (
                close,
                close + 0.2,
                close - 0.2,
                close,
                10.0 + index,
                base_ts + index * 60,
                4.0 + (index % 3),
            )
        )
    return rows


def _history_bars(length: int) -> list[dict[str, float]]:
    return [
        {
            "open": row[0],
            "high": row[1],
            "low": row[2],
            "close": row[3],
            "volume": row[4],
            "timestamp": row[5],
            "taker_buy_base": row[6],
        }
        for row in _history(length)
    ]


def _assert_feature_maps_close(actual: dict, expected: dict) -> None:
    assert set(actual) == set(expected)
    for key, expected_value in expected.items():
        _assert_values_close(actual[key], expected_value, path=key)


def _assert_values_close(actual, expected, *, path: str) -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict), path
        assert set(actual) == set(expected), path
        for key, nested_expected in expected.items():
            _assert_values_close(actual[key], nested_expected, path=f"{path}.{key}")
        return

    if isinstance(expected, float):
        if math.isnan(expected):
            assert isinstance(actual, float) and math.isnan(actual), path
            return
        assert actual == pytest.approx(expected), path
        return

    assert actual == expected, path


class _FakeIndicator:
    lookback_required = 4


class _FakeRawIndicators:
    def __init__(
        self,
        *,
        snapshot: dict,
        live: dict | None = None,
        unprimed: list[str] | None = None,
    ) -> None:
        self.indicators = [_FakeIndicator()]
        self.snapshot = snapshot
        self.live = live or snapshot
        self.unprimed = unprimed or []
        self.prime_calls: list[list[tuple[float, ...]]] = []
        self.process_tick_calls: list[tuple[float, ...]] = []

    def prime(self, history: list[tuple[float, ...]]) -> None:
        self.prime_calls.append(history)

    def get_unprimed_indicator_keys(self) -> list[str]:
        return self.unprimed

    def snapshot_features(self, history: list[tuple[float, ...]]) -> dict:
        return dict(self.snapshot)

    def process_tick(self, data: tuple[float, ...]) -> dict:
        self.process_tick_calls.append(data)
        return dict(self.live)
