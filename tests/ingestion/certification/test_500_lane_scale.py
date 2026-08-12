from __future__ import annotations

import asyncio
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.providers.base import LiveStreamInterrupted
from apps.ingestion_app.runtime.controller import RuntimeController
from apps.ingestion_app.runtime.supervisor import RuntimeSupervisor
from apps.ingestion_app.settings import load_ingestion_settings
from libs.common.config import ConfigManager

from .conftest import (
    BASE_DURATION,
    BOUNDARY,
    ORIGIN,
    BlockingStream,
    ControlledLiveProvider,
    ControlledRepository,
    FakeSDKClient,
    FakeSupervisor,
    RecordingHTF,
    RecordingIngestion,
    RecordingRecovery,
    canonical,
    observation,
    synthetic_lanes,
    synthetic_settings,
    yield_control,
)


def _write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _message(
    open_time: datetime,
    *,
    symbol: str,
    closed: bool,
    interval: str = "1m",
) -> dict[str, Any]:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    open_ms = int((open_time - epoch).total_seconds() * 1000)
    close_ms = open_ms + 59_999
    return {
        "stream": f"{symbol.lower()}@kline_{interval}",
        "data": {
            "e": "kline",
            "s": symbol,
            "k": {
                "e": "kline",
                "s": symbol,
                "i": interval,
                "t": open_ms,
                "T": close_ms,
                "o": "100.0",
                "h": "101.0",
                "l": "99.0",
                "c": "100.5",
                "v": "10.0",
                "V": "12.5",
                "Q": "9999.0",
                "x": closed,
            },
        },
    }


async def _start_sdk_stream(
    manager: Any,
    subscriptions: dict[MarketLane, str],
    clients: list[FakeSDKClient],
    *,
    anchor: datetime = BOUNDARY,
) -> tuple[Any, asyncio.Task[Any], FakeSDKClient]:
    stream = manager.stream_closed_candles(
        subscriptions,
        base_timeframe="1m",
        timeframe_duration=BASE_DURATION,
        alignment_origin=ORIGIN,
        connection_anchor=anchor,
    )
    next_item = asyncio.create_task(stream.__anext__())
    for _ in range(4):
        await yield_control()
    assert clients
    return stream, next_item, clients[0]


def _sdk_manager(clients: list[FakeSDKClient], *, queue_maxsize: int = 1000):
    def factory(**kwargs: Any) -> FakeSDKClient:
        client = FakeSDKClient(**kwargs)
        clients.append(client)
        return client

    from apps.ingestion_app.runtime.websocket import BinanceWebSocketManager

    return BinanceWebSocketManager(
        stream_url="wss://example.test/market",
        queue_maxsize=queue_maxsize,
        client_factory=factory,
    )


def test_500_temporary_asset_files_load_with_deterministic_serialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = synthetic_settings(500, full_timeframes=True)
    dumped = settings.model_dump()
    global_dump = {
        "ingestion": {key: value for key, value in dumped.items() if key != "assets"}
    }
    config_root = tmp_path / "configs"
    _write_yaml(config_root / "ingestion" / "global.yaml", global_dump)
    for asset_name, asset in dumped["assets"].items():
        _write_yaml(config_root / "ingestion" / "assets" / f"{asset_name}.yaml", asset)

    monkeypatch.chdir(tmp_path)
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(config_root))
    started = time.perf_counter()
    try:
        loaded = load_ingestion_settings(manager)
        validation_seconds = time.perf_counter() - started
        serialized_once = loaded.model_dump_json()
        serialized_twice = loaded.model_dump_json()

        assert len(loaded.assets) == 500
        assert sum(len(asset.instruments) for asset in loaded.assets.values()) == 500
        assert len(synthetic_lanes(loaded)) == 500
        assert all(
            instrument.live_provider == "binance_native"
            and set(instrument.provider_symbols) == {"binance_native", "ccxt_binance"}
            for asset in loaded.assets.values()
            for instrument in asset.instruments.values()
        )
        assert serialized_once == serialized_twice
        assert validation_seconds >= 0

        with pytest.raises(TypeError):
            loaded.assets["G0SYN0000"] = loaded.assets["G0SYN0000"]  # type: ignore[index]
        with pytest.raises(TypeError):
            loaded.assets["G0SYN0000"].instruments[  # type: ignore[index]
                "G0SYN0000-USDT-PERP"
            ] = loaded.assets["G0SYN0000"].instruments["G0SYN0000-USDT-PERP"]
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()

    assert not list(tmp_path.rglob("*.tmp"))


def test_synthetic_settings_defaults_match_production_v2_global_config() -> None:
    repository_root = Path(__file__).parents[3]
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(repository_root / "configs"))
    try:
        production = load_ingestion_settings(manager)
        synthetic = synthetic_settings(1, full_timeframes=True)
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()

    assert synthetic.base_timeframe == production.base_timeframe
    assert synthetic.calendar.type == production.calendar.type
    assert synthetic.calendar.timezone == production.calendar.timezone
    assert synthetic.calendar.alignment_origin == production.calendar.alignment_origin
    assert synthetic.websocket.queue_maxsize == production.websocket.queue_maxsize
    assert synthetic.recovery.max_concurrency == production.recovery.max_concurrency
    assert synthetic.recovery.page_limit == production.recovery.page_limit
    assert (
        synthetic.recovery.max_attempts_per_provider
        == production.recovery.max_attempts_per_provider
    )
    assert (
        synthetic.recovery.retry_backoff_seconds
        == production.recovery.retry_backoff_seconds
    )
    assert (
        synthetic.recovery.rest_finalization_grace_seconds
        == production.recovery.rest_finalization_grace_seconds
    )
    assert synthetic.publication.batch_size == production.publication.batch_size
    assert synthetic.publication.stream_maxlen == production.publication.stream_maxlen
    assert (
        synthetic.publication.stream_approximate
        == production.publication.stream_approximate
    )
    assert (
        synthetic.publication.idle_sleep_seconds
        == production.publication.idle_sleep_seconds
    )
    assert (
        synthetic.publication.error_backoff_seconds
        == production.publication.error_backoff_seconds
    )
    assert {
        name: timeframe.duration_seconds
        for name, timeframe in synthetic.timeframes.items()
    } == {
        name: timeframe.duration_seconds
        for name, timeframe in production.timeframes.items()
    }


@pytest.mark.asyncio
async def test_500_lane_controller_validation_allocates_no_runtime_resources() -> None:
    settings = synthetic_settings(500)
    supervisors: list[FakeSupervisor] = []
    run_tasks_before = {
        task
        for task in asyncio.all_tasks()
        if task.get_name() == "ingestion-supervisor"
    }

    def factory(candidate):
        return FakeSupervisor(candidate, supervisors)

    controller = RuntimeController(settings=settings, supervisor_factory=factory)
    controller.validate_settings(settings)
    assert len(supervisors) == 1
    assert supervisors[0].run_calls == 0
    assert (
        not {
            task
            for task in asyncio.all_tasks()
            if task.get_name() == "ingestion-supervisor"
        }
        - run_tasks_before
    )

    await controller.start()
    await asyncio.wait_for(supervisors[-1].started.wait(), timeout=1)
    assert supervisors[-1].run_calls == 1
    assert (
        len(
            [
                task
                for task in asyncio.all_tasks()
                if task.get_name() == "ingestion-supervisor" and not task.done()
            ]
        )
        == 1
    )

    await controller.close()
    assert not [
        task
        for task in asyncio.all_tasks()
        if task.get_name() == "ingestion-supervisor" and not task.done()
    ]


@pytest.mark.asyncio
async def test_real_supervisor_resolves_500_lanes_and_opens_one_stream_after_maintenance() -> (
    None
):
    settings = synthetic_settings(500)
    lanes = synthetic_lanes(settings)
    latest = {
        lane: canonical(observation(lane, BOUNDARY - BASE_DURATION)) for lane in lanes
    }
    repository = ControlledRepository(latest=latest)
    provider = ControlledLiveProvider([BlockingStream()])
    htf = RecordingHTF()
    recovery = RecordingRecovery()
    supervisor = RuntimeSupervisor(
        settings=settings,
        live_provider=provider,
        repository=repository,  # type: ignore[arg-type]
        ingestion_service=RecordingIngestion(),  # type: ignore[arg-type]
        htf_service=htf,  # type: ignore[arg-type]
        recovery_engine=recovery,  # type: ignore[arg-type]
        now_fn=lambda: BOUNDARY + timedelta(seconds=30),
    )

    task = asyncio.create_task(supervisor.run(), name="certification-supervisor")
    for _ in range(20):
        await yield_control()
        if provider.calls:
            break
    assert len(provider.calls) == 1
    assert len(provider.calls[0]) == 500
    assert len(set(provider.calls[0].values())) == 500
    assert recovery.calls == []
    assert len(htf.latest_calls) == 500
    assert provider.stream_kwargs[0]["connection_anchor"] == BOUNDARY

    supervisor.stop()
    await asyncio.wait_for(task, timeout=2)
    assert provider.created_streams[0].closed
    assert supervisor.snapshot().state.name == "STOPPED"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream_count", [500, 1024])
async def test_external_subscription_headroom_is_one_sorted_batched_connection(
    stream_count: int,
) -> None:
    clients: list[FakeSDKClient] = []
    manager = _sdk_manager(clients)
    subscriptions = {
        MarketLane("binance", f"SYN-{index:04d}-PERP", "1m"): f"SYN{index:04d}USDT"
        for index in range(stream_count)
    }
    stream, next_item, client = await _start_sdk_stream(manager, subscriptions, clients)

    assert len(clients) == 1
    assert len(client.subscribe_calls) == 1
    names = client.subscribe_calls[0]
    assert len(names) == stream_count
    assert len(set(names)) == stream_count
    assert names == sorted(names)
    assert all(name.endswith("@kline_1m") for name in names)
    assert not any("@kline_15m" in name for name in names)

    client.kwargs["on_close"](client)
    with pytest.raises(LiveStreamInterrupted):
        await next_item
    await stream.aclose()
    assert client.stop_calls == 1


@pytest.mark.asyncio
async def test_5000_forming_messages_never_enter_finalized_delivery() -> None:
    settings = synthetic_settings(500)
    lanes = synthetic_lanes(settings)
    clients: list[FakeSDKClient] = []
    manager = _sdk_manager(clients)
    subscriptions = {lane: f"G0SYN{index:04d}USDT" for index, lane in enumerate(lanes)}
    stream, next_item, client = await _start_sdk_stream(manager, subscriptions, clients)

    messages = [
        _message(
            BOUNDARY,
            symbol=symbol,
            closed=False,
        )
        for symbol in subscriptions.values()
        for _ in range(10)
    ]
    producer = threading.Thread(
        target=lambda: [client.emit_from_thread(message) for message in messages],
        name="certification-forming-producer",
    )
    producer.start()
    producer.join(timeout=2)
    assert not producer.is_alive()
    for _ in range(10):
        await yield_control()
    assert not next_item.done()

    client.kwargs["on_close"](client)
    with pytest.raises(LiveStreamInterrupted) as raised:
        await next_item
    assert raised.value.reason == "websocket_disconnected"
    await stream.aclose()


async def _collect_wave(
    *,
    wave_count: int,
) -> tuple[list[Any], FakeSDKClient, Any, threading.Thread]:
    settings = synthetic_settings(500)
    lanes = synthetic_lanes(settings)
    clients: list[FakeSDKClient] = []
    manager = _sdk_manager(clients)
    subscriptions = {lane: f"G0SYN{index:04d}USDT" for index, lane in enumerate(lanes)}
    stream = manager.stream_closed_candles(
        subscriptions,
        base_timeframe="1m",
        timeframe_duration=BASE_DURATION,
        alignment_origin=ORIGIN,
        connection_anchor=BOUNDARY,
    )
    received: list[Any] = []

    async def consume() -> None:
        async for item in stream:
            received.append(item)
            if len(received) == 500 * wave_count:
                break

    consumer = asyncio.create_task(consume())
    for _ in range(5):
        await yield_control()
    assert clients
    client = clients[0]
    messages = [
        _message(
            BOUNDARY + wave * BASE_DURATION,
            symbol=symbol,
            closed=True,
        )
        for wave in range(wave_count)
        for symbol in subscriptions.values()
    ]
    producer = threading.Thread(
        target=lambda: [client.emit_from_thread(message) for message in messages],
        name="certification-closed-wave-producer",
    )
    producer.start()
    producer.join(timeout=3)
    assert not producer.is_alive()
    await asyncio.wait_for(consumer, timeout=5)
    await stream.aclose()
    return received, client, stream, producer


@pytest.mark.asyncio
async def test_one_500_lane_finalized_wave_is_lossless_and_decimal_normalized() -> None:
    received, client, _stream, producer = await _collect_wave(wave_count=1)

    assert len(received) == 500
    assert len({item.lane for item in received}) == 500
    assert len({(item.lane, item.open_time) for item in received}) == 500
    assert all(item.volume.is_finite() for item in received)
    assert all(str(item.taker_buy_base) == "12.5" for item in received)
    assert client.stop_calls == 1
    assert not producer.is_alive()


@pytest.mark.asyncio
async def test_two_500_lane_finalized_waves_fit_and_preserve_per_lane_order() -> None:
    received, client, _stream, _producer = await _collect_wave(wave_count=2)

    assert len(received) == 1000
    by_lane: dict[MarketLane, list[datetime]] = defaultdict(list)
    for item in received:
        by_lane[item.lane].append(item.open_time)
    assert len(by_lane) == 500
    assert all(
        times == [BOUNDARY, BOUNDARY + BASE_DURATION] for times in by_lane.values()
    )
    assert client.stop_calls == 1


@pytest.mark.asyncio
async def test_1001st_finalized_message_fails_closed_without_drop_oldest() -> None:
    settings = synthetic_settings(500)
    lanes = synthetic_lanes(settings)
    clients: list[FakeSDKClient] = []
    manager = _sdk_manager(clients)
    subscriptions = {lane: f"G0SYN{index:04d}USDT" for index, lane in enumerate(lanes)}
    stream, next_item, client = await _start_sdk_stream(
        manager,
        subscriptions,
        clients,
        anchor=BOUNDARY,
    )
    messages = [
        _message(BOUNDARY + wave * BASE_DURATION, symbol=symbol, closed=True)
        for wave in range(2)
        for symbol in subscriptions.values()
    ]
    messages.append(
        _message(
            BOUNDARY + 2 * BASE_DURATION,
            symbol=next(iter(subscriptions.values())),
            closed=True,
        )
    )
    producer = threading.Thread(
        target=lambda: [client.emit_from_thread(message) for message in messages],
        name="certification-overflow-producer",
    )
    producer.start()
    producer.join(timeout=3)
    assert not producer.is_alive()
    with pytest.raises(LiveStreamInterrupted) as raised:
        await asyncio.wait_for(next_item, timeout=5)
    assert raised.value.reason == "websocket_queue_overflow"
    assert client.stop_calls == 1
    await stream.aclose()
