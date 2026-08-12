from __future__ import annotations

import asyncio

import pytest

from apps.signal_app.catalog.static import StaticSignalPairCatalog
from apps.signal_app.models import SignalPair
from apps.signal_app.runtime.runner import SignalRuntimeRunner
from apps.signal_app.settings import SignalWorkerSettings
from libs.common.asset_manifest import ASSET_LIFECYCLE_STREAM


class _FakeLifecycleRedis:
    def __init__(self) -> None:
        self.groups: list[tuple[str, str, str, bool]] = []
        self.acks: list[tuple[str, str, str]] = []
        self.hashes: dict[str, dict[str, str]] = {}
        self.deleted: list[str] = []
        self._queue: asyncio.Queue[tuple[str, dict[str, str]]] = asyncio.Queue()

    async def xgroup_create(self, stream_key: str, group_name: str, id: str = "0", mkstream: bool = True):
        self.groups.append((stream_key, group_name, id, mkstream))

    async def xreadgroup(self, group_name: str, consumer_name: str, streams, count: int = 1, block: int = 1000):
        try:
            message = await asyncio.wait_for(self._queue.get(), timeout=max(block / 1000, 0.05))
        except asyncio.TimeoutError:
            return []
        return [(ASSET_LIFECYCLE_STREAM, [message])]

    async def xack(self, stream: str, group: str, message_id: str):
        self.acks.append((stream, group, message_id))
        return 1

    async def hset(self, key: str, mapping: dict[str, str]):
        self.hashes[key] = dict(mapping)
        return len(mapping)

    async def hgetall(self, key: str):
        return dict(self.hashes.get(key, {}))

    async def delete(self, key: str):
        self.deleted.append(key)
        self.hashes.pop(key, None)
        return 1

    async def set(self, key: str, value: str, *, ex: int | None = None, nx: bool = False):
        if nx and key in self.hashes:
            return False
        self.hashes[key] = {"value": value, "ex": str(ex) if ex is not None else ""}
        return True

    async def emit(self, message_id: str, payload: dict[str, str]) -> None:
        await self._queue.put((message_id, payload))


class _StubWorker:
    created: list["_StubWorker"] = []

    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        settings: SignalWorkerSettings,
        base_timeframe: str = "1m",
        trigger_timeframe: str | None = None,
        trigger_mode: str = "on_bar_close",
        required_context_profiles: list[str] | None = None,
    ) -> None:
        self.asset = asset
        self.timeframe = timeframe
        self.base_timeframe = base_timeframe
        self.trigger_timeframe = trigger_timeframe or timeframe
        self.trigger_mode = trigger_mode
        self.required_context_profiles = list(required_context_profiles or [])
        self.connected = False
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        _StubWorker.created.append(self)

    async def connect(self, redis_client) -> None:
        self.connected = redis_client is not None

    async def start(self) -> None:
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


@pytest.mark.asyncio
async def test_signal_runtime_runner_reacts_to_pause_and_resume_lifecycle_events() -> None:
    _StubWorker.created = []
    redis = _FakeLifecycleRedis()
    runner = SignalRuntimeRunner(
        catalog=StaticSignalPairCatalog([SignalPair(asset="BTCUSDT", timeframe="1h")]),
        worker_factory=_StubWorker,
        worker_settings=SignalWorkerSettings(consumer_group="signal_lifecycle_test"),
    )

    await runner.connect(redis)
    start_task = asyncio.create_task(runner.start())
    await _StubWorker.created[0].started.wait()

    await redis.emit(
        "1-0",
        {
            "event_id": "evt-pause",
            "event_type": "ASSET_PAUSED",
            "command_type": "PAUSE_ASSET",
            "symbol": "BTCUSDT",
            "base_timeframe": "1m",
            "publish_timeframes": '["1h"]',
            "timeframes": '["1m","1h"]',
            "enabled": "True",
            "desired_state": "PAUSED",
            "requested_by": "test",
            "reason": "pause",
            "emitted_at": "1",
        },
    )
    await asyncio.wait_for(_StubWorker.created[0].cancelled.wait(), timeout=2)

    await redis.emit(
        "2-0",
        {
            "event_id": "evt-resume",
            "event_type": "ASSET_RESUMED",
            "command_type": "RESUME_ASSET",
            "symbol": "BTCUSDT",
            "base_timeframe": "1m",
            "publish_timeframes": '["1h"]',
            "timeframes": '["1m","1h"]',
            "enabled": "True",
            "desired_state": "LIVE",
            "requested_by": "test",
            "reason": "resume",
            "emitted_at": "2",
        },
    )
    async def _resumed_workers_started() -> None:
        while len(_StubWorker.created) < 2:
            await asyncio.sleep(0.01)
        await _StubWorker.created[1].started.wait()

    await asyncio.wait_for(_resumed_workers_started(), timeout=2)

    await runner.stop()
    await start_task

    assert len(_StubWorker.created) == 2
    assert redis.acks == [
        (ASSET_LIFECYCLE_STREAM, "signal_lifecycle_test", "1-0"),
        (ASSET_LIFECYCLE_STREAM, "signal_lifecycle_test", "2-0"),
    ]


@pytest.mark.asyncio
async def test_signal_runtime_runner_deduplicates_replayed_lifecycle_event_ids() -> None:
    _StubWorker.created = []
    redis = _FakeLifecycleRedis()
    runner = SignalRuntimeRunner(
        catalog=StaticSignalPairCatalog([SignalPair(asset="BTCUSDT", timeframe="1h")]),
        worker_factory=_StubWorker,
        worker_settings=SignalWorkerSettings(consumer_group="signal_lifecycle_dedup_test"),
    )

    await runner.connect(redis)
    start_task = asyncio.create_task(runner.start())
    await _StubWorker.created[0].started.wait()

    pause_payload = {
        "event_id": "evt-pause",
        "event_type": "ASSET_PAUSED",
        "command_type": "PAUSE_ASSET",
        "symbol": "BTCUSDT",
        "base_timeframe": "1m",
        "publish_timeframes": '["1h"]',
        "timeframes": '["1m","1h"]',
        "enabled": "True",
        "desired_state": "PAUSED",
        "requested_by": "test",
        "reason": "pause",
        "emitted_at": "1",
    }
    await redis.emit("1-0", pause_payload)
    await asyncio.wait_for(_StubWorker.created[0].cancelled.wait(), timeout=2)
    await redis.emit("2-0", pause_payload)
    await asyncio.sleep(0.1)

    await runner.stop()
    await start_task

    assert len(_StubWorker.created) == 1


@pytest.mark.asyncio
async def test_signal_runtime_runner_uses_full_catalog_metadata_for_lifecycle_additions() -> None:
    _StubWorker.created = []
    redis = _FakeLifecycleRedis()
    runner = SignalRuntimeRunner(
        catalog=StaticSignalPairCatalog(
            [
                SignalPair(
                    asset="BTCUSDT",
                    timeframe="1h",
                    base_timeframe="1m",
                    required_context_profiles=["volatility_60m"],
                ),
                SignalPair(
                    asset="BTCUSDT",
                    timeframe="1m",
                    base_timeframe="1m",
                    required_context_profiles=["volatility_60m"],
                ),
            ]
        ),
        initial_pairs=[SignalPair(asset="BTCUSDT", timeframe="1h", source="asset_manifest")],
        worker_factory=_StubWorker,
        worker_settings=SignalWorkerSettings(consumer_group="signal_lifecycle_metadata_test"),
    )

    await runner.connect(redis)
    start_task = asyncio.create_task(runner.start())
    await _StubWorker.created[0].started.wait()

    await redis.emit(
        "1-0",
        {
            "event_id": "evt-resume",
            "event_type": "ASSET_RESUMED",
            "command_type": "RESUME_ASSET",
            "symbol": "BTCUSDT",
            "base_timeframe": "1m",
            "publish_timeframes": '["1h"]',
            "timeframes": '["1m","1h"]',
            "enabled": "True",
            "desired_state": "LIVE",
            "requested_by": "test",
            "reason": "resume",
            "emitted_at": "2",
        },
    )

    async def _resumed_workers_started() -> None:
        while len(_StubWorker.created) < 2:
            await asyncio.sleep(0.01)
        await _StubWorker.created[1].started.wait()

    await asyncio.wait_for(_resumed_workers_started(), timeout=2)
    await runner.stop()
    await start_task

    resumed_pairs = {(worker.asset, worker.timeframe): worker for worker in _StubWorker.created}
    assert resumed_pairs[("BTCUSDT", "1m")].required_context_profiles == ["volatility_60m"]


@pytest.mark.asyncio
async def test_signal_runtime_runner_clears_app_streams_on_remove() -> None:
    _StubWorker.created = []
    redis = _FakeLifecycleRedis()
    runner = SignalRuntimeRunner(
        catalog=StaticSignalPairCatalog(
            [
                SignalPair(asset="BTCUSDT", timeframe="1h"),
                SignalPair(
                    asset="BTCUSDT",
                    timeframe="4h",
                    trigger_timeframe="1m",
                    trigger_mode="on_base_bar_close",
                    base_timeframe="1m",
                ),
            ]
        ),
        worker_factory=_StubWorker,
        worker_settings=SignalWorkerSettings(consumer_group="signal_lifecycle_remove_test"),
    )

    await runner.connect(redis)
    start_task = asyncio.create_task(runner.start())
    await asyncio.gather(*[worker.started.wait() for worker in _StubWorker.created[:2]])

    await redis.emit(
        "3-0",
        {
            "event_id": "evt-remove",
            "event_type": "ASSET_REMOVE_REQUESTED",
            "command_type": "REMOVE_ASSET",
            "symbol": "BTCUSDT",
            "base_timeframe": "1m",
            "publish_timeframes": '["1h","4h"]',
            "timeframes": '["1m","1h","4h"]',
            "enabled": "False",
            "desired_state": "REMOVING",
            "requested_by": "test",
            "reason": "remove",
            "emitted_at": "3",
        },
    )

    async def _workers_cancelled() -> None:
        await asyncio.gather(*[worker.cancelled.wait() for worker in _StubWorker.created[:2]])

    await asyncio.wait_for(_workers_cancelled(), timeout=2)
    await asyncio.sleep(0.05)

    await runner.stop()
    await start_task

    assert "signal:status:BTCUSDT:1h" in redis.deleted
    assert "signal:status:BTCUSDT:4h@1m" in redis.deleted
    assert "features:BTCUSDT:1h" in redis.deleted
    assert "features:BTCUSDT:4h@1m" in redis.deleted
    assert "price_update:BTCUSDT:1h" in redis.deleted
    assert "price_update:BTCUSDT:4h" in redis.deleted


@pytest.mark.asyncio
async def test_signal_runtime_runner_scales_to_large_pair_counts() -> None:
    _StubWorker.created = []
    redis = _FakeLifecycleRedis()
    pairs = [
        SignalPair(asset=f"ASSET{i:03d}", timeframe=timeframe)
        for i in range(200)
        for timeframe in ("1h", "4h")
    ]
    runner = SignalRuntimeRunner(
        catalog=StaticSignalPairCatalog(pairs),
        worker_factory=_StubWorker,
        worker_settings=SignalWorkerSettings(consumer_group="signal_scale_test"),
    )

    workers = await runner.connect(redis)
    assert len(workers) == 400

    async def _all_started() -> None:
        await asyncio.gather(*(worker.started.wait() for worker in _StubWorker.created))

    await asyncio.wait_for(_all_started(), timeout=5)
    await runner.stop()

    assert len(_StubWorker.created) == 400
    assert len(runner.workers) == 0
