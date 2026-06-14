from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.strategy_app.observability.runtime_state import (
    StrategyRuntimeStateStore,
    runtime_status_key,
)
from apps.strategy_app.observability.status import StrategyObservabilityService
from apps.strategy_app.control import StrategyControlStore, StrategyDesiredState
from apps.strategy_app.state import StrategyPair, StrategyPairState, StrategyRuntimeStatus
from libs.contracts.schemas import FeatureVector, ModelOutput, valkey_encode


class _MemoryRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.stream_messages: list[tuple[tuple, dict]] = []

    async def xgroup_create(self, *args, **kwargs) -> None:
        return None

    async def hset(self, key: str, mapping: dict[str, str]) -> None:
        self.hashes[key] = dict(mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        return self.hashes.get(key, {})

    async def xadd(self, *args, **kwargs) -> str:
        self.stream_messages.append((args, kwargs))
        return "1-0"

    async def aclose(self) -> None:
        return None


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


@pytest.mark.asyncio
@patch("apps.strategy_app.strategy_worker.ModelManager")
@patch("apps.strategy_app.strategy_worker.ScoringModelManager")
async def test_strategy_worker_updates_runtime_state_live(MockSMM, MockMM) -> None:
    from apps.strategy_app.strategy_worker import StrategyWorker

    mock_mm = MagicMock()
    mock_mm.evaluate.return_value = [_make_model_output(direction=1)]
    mock_mm.evaluate_adapted.return_value = []
    mock_mm.evaluate_scoring.return_value = []
    mock_mm.evaluate_shadow.return_value = []
    MockMM.return_value = mock_mm

    mock_smm = MagicMock()
    mock_smm.evaluate.return_value = []
    MockSMM.return_value = mock_smm

    worker = StrategyWorker("BTCUSDT", "4h")
    redis = _MemoryRedis()
    await worker.connect(redis)

    await worker.process_features(valkey_encode(_make_feature_vector()))

    store = StrategyRuntimeStateStore(redis)
    status = await store.read(StrategyPair(asset="BTCUSDT", timeframe="4h"))

    assert status is not None
    assert status.state == StrategyPairState.LIVE
    assert status.last_feature_ts == 1_700_000_000.0
    assert status.last_signal_ts == 1_700_000_000.0
    assert status.detail["published_count"] == 1


@pytest.mark.asyncio
@patch("apps.strategy_app.strategy_worker.ModelManager")
async def test_strategy_worker_updates_runtime_state_on_decode_error(MockMM) -> None:
    from apps.strategy_app.strategy_worker import StrategyWorker

    MockMM.return_value = MagicMock()
    worker = StrategyWorker("BTCUSDT", "4h")
    redis = _MemoryRedis()
    await worker.connect(redis)

    await worker.process_features({"garbage_key": "garbage_value"})

    store = StrategyRuntimeStateStore(redis)
    status = await store.read(StrategyPair(asset="BTCUSDT", timeframe="4h"))

    assert status is not None
    assert status.state == StrategyPairState.DEGRADED
    assert status.detail["phase"] == "decode"
    assert status.last_error


@pytest.mark.asyncio
@patch("apps.strategy_app.strategy_worker.ModelManager")
@patch("apps.strategy_app.strategy_worker.ScoringModelManager")
async def test_strategy_worker_skips_publish_when_paused(MockSMM, MockMM) -> None:
    from apps.strategy_app.strategy_worker import StrategyWorker

    mock_mm = MagicMock()
    mock_mm.evaluate.return_value = [_make_model_output(direction=1)]
    mock_mm.evaluate_adapted.return_value = []
    mock_mm.evaluate_scoring.return_value = []
    mock_mm.evaluate_shadow.return_value = []
    MockMM.return_value = mock_mm

    mock_smm = MagicMock()
    mock_smm.evaluate.return_value = []
    MockSMM.return_value = mock_smm

    worker = StrategyWorker("BTCUSDT", "4h")
    redis = _MemoryRedis()
    await worker.connect(redis)
    control_store = StrategyControlStore(redis)
    await control_store.set_desired_state(
        StrategyPair(asset="BTCUSDT", timeframe="4h"),
        StrategyDesiredState.PAUSED,
        reason="maintenance",
    )

    await worker.process_features(valkey_encode(_make_feature_vector()))

    mock_mm.evaluate.assert_not_called()
    assert redis.stream_messages == []
    status = await StrategyRuntimeStateStore(redis).read(StrategyPair(asset="BTCUSDT", timeframe="4h"))
    assert status is not None
    assert status.state == StrategyPairState.PAUSED
    assert status.detail["desired_state"] == StrategyDesiredState.PAUSED.value


@pytest.mark.asyncio
async def test_strategy_observability_service_reads_persisted_runtime_state() -> None:
    persisted = StrategyRuntimeStatus(
        pair=StrategyPair(asset="BTCUSDT", timeframe="1h"),
        state=StrategyPairState.DEGRADED,
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
                "direction": "1",
                "conviction": "0.82",
                "price": "105.0",
                "metadata": '{"selection_rank": 1}',
            },
        )
    ]

    async def hgetall(key: str):
        if key == runtime_status_key("BTCUSDT", "1h"):
            return valkey_encode(persisted, inject_trace=False)
        return {}

    redis_client.hgetall.side_effect = hgetall

    service = StrategyObservabilityService(
        redis_client,
        [StrategyPair(asset="BTCUSDT", timeframe="1h")],
    )

    status = await service.status()

    assert status["BTCUSDT:1h"].state == StrategyPairState.DEGRADED
    assert status["BTCUSDT:1h"].last_error == "bootstrap degraded"
    assert status["BTCUSDT:1h"].last_signal_ts == 1_700_000_300_000.0
    assert status["BTCUSDT:1h"].detail["phase"] == "bootstrap"
    assert status["BTCUSDT:1h"].detail["latest_status"] == "ok"


@pytest.mark.asyncio
async def test_strategy_status_route_returns_runtime_status(monkeypatch) -> None:
    from apps.api_app.routers.strategy import strategy_status

    redis_client = AsyncMock()
    redis_client.xrevrange.return_value = [
        (
            "1-0",
            {
                "timestamp": "1700000000000",
                "direction": "1",
                "conviction": "0.82",
                "price": "105.0",
                "metadata": '{"selection_rank": 1}',
            },
        )
    ]
    redis_client.hgetall.return_value = {}
    redis_client.aclose = AsyncMock()

    monkeypatch.setattr(
        "apps.api_app.routers.strategy.discover_pairs",
        lambda _config: [("BTCUSDT", "1h")],
    )
    monkeypatch.setattr(
        "apps.api_app.routers.strategy.create_valkey_client",
        AsyncMock(return_value=redis_client),
    )

    status = await strategy_status()

    assert status["BTCUSDT:1h"].pair.asset == "BTCUSDT"
    assert status["BTCUSDT:1h"].state == StrategyPairState.LIVE
    assert status["BTCUSDT:1h"].last_signal_ts == 1_700_000_000_000.0
    assert status["BTCUSDT:1h"].detail["latest_status"] == "ok"
    redis_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_pause_resume_routes_update_strategy_control_and_runtime(monkeypatch) -> None:
    from apps.api_app.routers.strategy import (
        StrategyActionRequest,
        pause_strategy_pair,
        resume_strategy_pair,
    )

    redis = _MemoryRedis()
    monkeypatch.setattr(
        "apps.api_app.routers.strategy.discover_pairs",
        lambda _config: [("BTCUSDT", "1h")],
    )
    monkeypatch.setattr(
        "apps.api_app.routers.strategy.create_valkey_client",
        AsyncMock(return_value=redis),
    )

    paused = await pause_strategy_pair(
        "BTCUSDT",
        "1h",
        StrategyActionRequest(reason="maintenance"),
    )
    resumed = await resume_strategy_pair(
        "BTCUSDT",
        "1h",
        StrategyActionRequest(reason="done"),
    )

    assert paused.desired_state == StrategyDesiredState.PAUSED
    assert resumed.desired_state == StrategyDesiredState.LIVE

    control = await StrategyControlStore(redis).read(StrategyPair(asset="BTCUSDT", timeframe="1h"))
    runtime = await StrategyRuntimeStateStore(redis).read(StrategyPair(asset="BTCUSDT", timeframe="1h"))

    assert control is not None
    assert control.desired_state == StrategyDesiredState.LIVE
    assert runtime is not None
    assert runtime.state == StrategyPairState.WARMING
    assert runtime.detail["desired_state"] == StrategyDesiredState.LIVE.value
