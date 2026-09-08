from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

import apps.ingestion_app.runtime.websocket as websocket_module
from apps.ingestion_app.domain.candle import CandleObservation
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.providers.base import (
    LiveCandleProvider,
    LiveStreamInterrupted,
    TransportDeadlineExceeded,
)
from apps.ingestion_app.runtime.websocket import (
    BinanceWebSocketManager,
    _build_recovery_requests,
)
from apps.ingestion_app.services.time_alignment import aligned_bucket_start
from libs.common.exceptions import DataIngestionError

ORIGIN = datetime(1970, 1, 5, tzinfo=UTC)
DURATION = timedelta(minutes=1)
LANE = MarketLane("binance", "BTC-TEST-PERP", "1m")
SYMBOL = "BTCUSDT"


class _CountingDateTime(datetime):
    calls = 0
    values = (
        datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC),
    )

    @classmethod
    def now(cls, tz: object = None) -> datetime:
        value = cls.values[cls.calls]
        cls.calls += 1
        if tz is not None:
            value = value.astimezone(tz)  # type: ignore[arg-type]
        return cls(
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            tzinfo=value.tzinfo,
        )


def _milliseconds(value: datetime) -> int:
    elapsed = value - datetime(1970, 1, 1, tzinfo=UTC)
    return (
        elapsed.days * 86_400_000
        + elapsed.seconds * 1_000
        + elapsed.microseconds // 1_000
    )


def _current_anchor() -> datetime:
    return aligned_bucket_start(datetime.now(UTC), DURATION, ORIGIN)


def _message(
    open_time: datetime,
    *,
    symbol: str = SYMBOL,
    interval: str = "1m",
    closed: object = True,
    open_value: object = "100.0",
    close_adjust_ms: int = 0,
    taker_buy_base: object = "12.5",
    taker_buy_quote: object = "9999.0",
    include_close_flag: bool = True,
) -> dict[str, Any]:
    kline: dict[str, Any] = {
        "e": "kline",
        "s": symbol,
        "i": interval,
        "t": _milliseconds(open_time),
        "T": _milliseconds(open_time + DURATION - timedelta(milliseconds=1))
        + close_adjust_ms,
        "o": open_value,
        "h": "101.0",
        "l": "99.0",
        "c": "100.5",
        "v": "20.0",
        "V": taker_buy_base,
        "Q": taker_buy_quote,
    }
    if include_close_flag:
        kline["x"] = closed
    return {
        "stream": f"{symbol.lower()}@kline_{interval}",
        "data": {"e": "kline", "s": symbol, "k": kline},
    }


class _FakeClient:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.subscribe_calls: list[list[str]] = []
        self.stop_calls = 0

    def subscribe(self, streams: list[str]) -> None:
        self.subscribe_calls.append(list(streams))

    def stop(self) -> None:
        self.stop_calls += 1

    def emit(self, message: object) -> None:
        self.kwargs["on_message"](self, message)

    def emit_from_thread(self, message: object) -> None:
        self.kwargs["on_message"](self, message)

    def close(self) -> None:
        self.kwargs["on_close"](self)

    def error(self, error: object) -> None:
        self.kwargs["on_error"](self, error)


def _manager(
    clients: list[_FakeClient],
    *,
    queue_maxsize: int = 1000,
    lifecycle_timeout_seconds: float = 30,
) -> BinanceWebSocketManager:
    def factory(**kwargs: Any) -> _FakeClient:
        client = _FakeClient(**kwargs)
        clients.append(client)
        return client

    return BinanceWebSocketManager(
        stream_url="wss://example.test",
        queue_maxsize=queue_maxsize,
        lifecycle_timeout_seconds=lifecycle_timeout_seconds,
        client_factory=factory,
    )


async def _start_stream(
    manager: BinanceWebSocketManager,
    clients: list[_FakeClient],
    *,
    subscriptions: dict[MarketLane, str] | None = None,
    connection_anchor: datetime | None = None,
) -> tuple[Any, asyncio.Task[Any], _FakeClient]:
    connection_anchor = connection_anchor or _current_anchor()
    stream = manager.stream_closed_candles(
        subscriptions or {LANE: SYMBOL},
        base_timeframe="1m",
        timeframe_duration=DURATION,
        alignment_origin=ORIGIN,
        connection_anchor=connection_anchor,
    )
    next_item = asyncio.create_task(stream.__anext__())
    for _ in range(100):
        await asyncio.sleep(0)
        if clients and clients[0].subscribe_calls:
            break
    assert clients and clients[0].subscribe_calls
    return stream, next_item, clients[0]


async def _wait_for_retained_workers(
    manager: BinanceWebSocketManager,
    expected: int,
    *,
    timeout: float = 1.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while manager.retained_worker_count != expected:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            pytest.fail(
                f"retained websocket worker count did not reach {expected}; "
                f"got {manager.retained_worker_count}"
            )
        await asyncio.sleep(min(0.01, remaining))


def test_websocket_lifecycle_timeout_defaults_to_thirty_seconds() -> None:
    manager = _manager([])

    assert manager.lifecycle_timeout_seconds == 30.0


@pytest.mark.parametrize(
    "timeout",
    [0, -1, False, "30", float("nan"), float("inf"), float("-inf")],
)
def test_websocket_lifecycle_timeout_rejects_invalid_values(
    timeout: object,
) -> None:
    with pytest.raises((TypeError, ValueError), match="lifecycle_timeout_seconds"):
        _manager([], lifecycle_timeout_seconds=timeout)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "subscriptions",
    [
        {},
        {"not-a-lane": SYMBOL},  # type: ignore[dict-item]
        {LANE: ""},
        {
            LANE: SYMBOL,
            MarketLane("binance", "ETH-TEST-PERP", "1m"): "btcusdt",
        },
        {MarketLane("binance", "BTC-TEST-PERP", "5m"): SYMBOL},
    ],
)
def test_subscription_validation_happens_before_client_construction(
    subscriptions: object,
) -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients)

    with pytest.raises((TypeError, ValueError)):
        manager.stream_closed_candles(
            subscriptions,  # type: ignore[arg-type]
            base_timeframe="1m",
            timeframe_duration=DURATION,
            alignment_origin=ORIGIN,
            connection_anchor=ORIGIN,
        )

    assert not clients


def test_subscription_validation_rejects_invalid_timing_inputs() -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients)

    with pytest.raises(ValueError):
        manager.stream_closed_candles(
            {LANE: SYMBOL},
            base_timeframe="1m",
            timeframe_duration=timedelta(0),
            alignment_origin=ORIGIN,
            connection_anchor=ORIGIN,
        )
    with pytest.raises(ValueError):
        manager.stream_closed_candles(
            {LANE: SYMBOL},
            base_timeframe="1m",
            timeframe_duration=DURATION,
            alignment_origin=datetime(2026, 1, 1, 5, 30),  # noqa: DTZ001
            connection_anchor=ORIGIN,
        )
    assert not clients


def test_subscription_validation_rejects_unaligned_connection_anchor() -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients)

    with pytest.raises(ValueError, match="connection_anchor"):
        manager.stream_closed_candles(
            {LANE: SYMBOL},
            base_timeframe="1m",
            timeframe_duration=DURATION,
            alignment_origin=ORIGIN,
            connection_anchor=ORIGIN + timedelta(seconds=1),
        )

    assert not clients


@pytest.mark.asyncio
async def test_factory_deadline_quarantines_and_retains_owned_worker() -> None:
    factory_started = threading.Event()
    release_factory = threading.Event()
    clients: list[_FakeClient] = []

    def factory(**kwargs: Any) -> _FakeClient:
        factory_started.set()
        release_factory.wait(5)
        client = _FakeClient(**kwargs)
        clients.append(client)
        return client

    manager = BinanceWebSocketManager(
        stream_url="wss://example.test",
        queue_maxsize=1,
        lifecycle_timeout_seconds=0.01,
        client_factory=factory,
    )
    stream = manager.stream_closed_candles(
        {LANE: SYMBOL},
        base_timeframe="1m",
        timeframe_duration=DURATION,
        alignment_origin=ORIGIN,
        connection_anchor=_current_anchor(),
    )
    next_item = asyncio.create_task(stream.__anext__())
    assert await asyncio.to_thread(factory_started.wait, 1)

    with pytest.raises(TransportDeadlineExceeded) as raised:
        await next_item

    assert raised.value.operation == "websocket factory"
    assert manager.lifecycle_quarantined is True
    assert manager.retained_worker_count == 1
    release_factory.set()
    await _wait_for_retained_workers(manager, 0)
    assert clients[0].stop_calls == 1

    reopened = manager.stream_closed_candles(
        {LANE: SYMBOL},
        base_timeframe="1m",
        timeframe_duration=DURATION,
        alignment_origin=ORIGIN,
        connection_anchor=_current_anchor(),
    )
    with pytest.raises(TransportDeadlineExceeded) as reopened_error:
        await reopened.__anext__()
    assert reopened_error.value.operation == "websocket factory"
    await stream.aclose()
    await reopened.aclose()


@pytest.mark.asyncio
async def test_subscription_deadline_quarantines_and_stops_after_release() -> None:
    subscription_started = threading.Event()
    release_subscription = threading.Event()
    clients: list[_FakeClient] = []

    class _HeldSubscribeClient(_FakeClient):
        def subscribe(self, streams: list[str]) -> None:
            subscription_started.set()
            release_subscription.wait(5)
            super().subscribe(streams)

    def factory(**kwargs: Any) -> _HeldSubscribeClient:
        client = _HeldSubscribeClient(**kwargs)
        clients.append(client)
        return client

    manager = BinanceWebSocketManager(
        stream_url="wss://example.test",
        queue_maxsize=1,
        lifecycle_timeout_seconds=0.01,
        client_factory=factory,
    )
    stream = manager.stream_closed_candles(
        {LANE: SYMBOL},
        base_timeframe="1m",
        timeframe_duration=DURATION,
        alignment_origin=ORIGIN,
        connection_anchor=_current_anchor(),
    )
    next_item = asyncio.create_task(stream.__anext__())
    assert await asyncio.to_thread(subscription_started.wait, 1)

    with pytest.raises(TransportDeadlineExceeded) as raised:
        await next_item

    assert raised.value.operation == "websocket subscribe"
    assert manager.lifecycle_quarantined is True
    assert manager.retained_worker_count == 1
    assert clients[0].stop_calls == 0
    release_subscription.set()
    await _wait_for_retained_workers(manager, 0)
    assert clients[0].stop_calls == 1

    reopened = manager.stream_closed_candles(
        {LANE: SYMBOL},
        base_timeframe="1m",
        timeframe_duration=DURATION,
        alignment_origin=ORIGIN,
        connection_anchor=_current_anchor(),
    )
    with pytest.raises(TransportDeadlineExceeded) as reopened_error:
        await reopened.__anext__()
    assert reopened_error.value.operation == "websocket subscribe"
    await stream.aclose()
    await reopened.aclose()


@pytest.mark.asyncio
async def test_stop_deadline_quarantines_until_owned_stop_finishes() -> None:
    stop_started = threading.Event()
    release_stop = threading.Event()
    clients: list[_FakeClient] = []

    class _HeldStopClient(_FakeClient):
        def stop(self) -> None:
            stop_started.set()
            release_stop.wait(5)
            super().stop()

    def factory(**kwargs: Any) -> _HeldStopClient:
        client = _HeldStopClient(**kwargs)
        clients.append(client)
        return client

    manager = BinanceWebSocketManager(
        stream_url="wss://example.test",
        queue_maxsize=1,
        lifecycle_timeout_seconds=0.01,
        client_factory=factory,
    )
    stream, first_item, client = await _start_stream(manager, clients)
    await _emit_and_receive(client, first_item, _message(_current_anchor()))

    try:
        with pytest.raises(TransportDeadlineExceeded) as raised:
            await stream.aclose()

        assert raised.value.operation == "websocket stop"
        assert stop_started.is_set()
        assert manager.lifecycle_quarantined is True
        assert manager.retained_worker_count == 1
        assert client.stop_calls == 0
    finally:
        release_stop.set()
    await _wait_for_retained_workers(manager, 0)
    assert client.stop_calls == 1

    reopened = manager.stream_closed_candles(
        {LANE: SYMBOL},
        base_timeframe="1m",
        timeframe_duration=DURATION,
        alignment_origin=ORIGIN,
        connection_anchor=_current_anchor(),
    )
    with pytest.raises(TransportDeadlineExceeded) as reopened_error:
        await reopened.__anext__()
    assert reopened_error.value.operation == "websocket stop"
    await stream.aclose()
    await reopened.aclose()


def test_recovery_requests_use_connection_or_consumed_anchor() -> None:
    connection_anchor = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    interruption_time = connection_anchor + timedelta(minutes=3, seconds=10)
    routes = {SYMBOL.casefold(): (LANE, SYMBOL)}

    before_progress = _build_recovery_requests(
        routes=routes,
        last_consumed_close={},
        connection_anchor=connection_anchor,
        interruption_time=interruption_time,
        timeframe_duration=DURATION,
        alignment_origin=ORIGIN,
        reason="websocket_disconnected",
    )
    after_progress = _build_recovery_requests(
        routes=routes,
        last_consumed_close={LANE: connection_anchor + DURATION},
        connection_anchor=connection_anchor,
        interruption_time=interruption_time,
        timeframe_duration=DURATION,
        alignment_origin=ORIGIN,
        reason="websocket_gap_detected",
    )

    assert before_progress[0].since == connection_anchor
    assert before_progress[0].until == connection_anchor + timedelta(minutes=3)
    assert before_progress[0].reason == "websocket_disconnected"
    assert after_progress[0].since == connection_anchor + DURATION
    assert after_progress[0].until == connection_anchor + timedelta(minutes=3)
    assert after_progress[0].reason == "websocket_gap_detected"


@pytest.mark.asyncio
async def test_multiple_lanes_use_one_batched_subscription_call() -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients)
    subscriptions = {
        LANE: SYMBOL,
        MarketLane("binance", "ETH-TEST-PERP", "1m"): "ETHUSDT",
    }
    stream, next_item, client = await _start_stream(
        manager,
        clients,
        subscriptions=subscriptions,
    )

    live_provider: LiveCandleProvider = manager
    assert live_provider.provider_id == "binance_native"
    assert client.subscribe_calls == [["btcusdt@kline_1m", "ethusdt@kline_1m"]]

    client.close()
    with pytest.raises(LiveStreamInterrupted) as raised:
        await next_item
    assert raised.value.reason == "websocket_disconnected"
    await stream.aclose()
    assert client.stop_calls == 1


@pytest.mark.asyncio
async def test_500_lanes_still_use_one_physical_connection_and_batch() -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients)
    subscriptions = {
        MarketLane("binance", f"TEST-{index:03d}", "1m"): f"SYM{index:03d}"
        for index in range(500)
    }
    stream, next_item, client = await _start_stream(
        manager,
        clients,
        subscriptions=subscriptions,
    )

    assert len(clients) == 1
    assert len(client.subscribe_calls) == 1
    assert len(client.subscribe_calls[0]) == 500
    assert client.subscribe_calls[0][0] == "sym000@kline_1m"
    assert client.subscribe_calls[0][-1] == "sym499@kline_1m"

    client.close()
    with pytest.raises(LiveStreamInterrupted):
        await next_item
    await stream.aclose()


@pytest.mark.asyncio
async def test_forming_update_is_ignored_and_closed_candle_uses_v_not_q() -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients)
    stream, next_item, client = await _start_stream(manager, clients)
    open_time = _current_anchor()

    client.emit({"result": None, "id": 1})
    await asyncio.sleep(0)
    assert not next_item.done()
    client.emit(_message(open_time, closed=False))
    await asyncio.sleep(0)
    assert not next_item.done()

    client.emit(
        _message(
            open_time,
            taker_buy_base="12.5",
            taker_buy_quote="9999.0",
        )
    )
    observation = await next_item

    assert observation.lane == LANE
    assert observation.provider_id == "binance_native"
    assert observation.provider_symbol == SYMBOL
    assert observation.transport == "websocket"
    assert observation.open_time == open_time
    assert observation.close_time == open_time + DURATION
    assert observation.provider_close_time == observation.close_time
    assert observation.open == Decimal("100.0")
    assert observation.volume == Decimal("20.0")
    assert observation.taker_buy_base == Decimal("12.5")
    await stream.aclose()
    assert client.stop_calls == 1


def test_websocket_received_at_clock_samples_only_at_observation_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(websocket_module, "datetime", _CountingDateTime)
    manager = _manager([])
    routes = {SYMBOL.casefold(): (LANE, SYMBOL)}

    def parse(message: object) -> CandleObservation | None:
        return manager._parse_message(
            message,
            routes=routes,
            base_timeframe="1m",
            timeframe_duration=DURATION,
            alignment_origin=ORIGIN,
        )

    assert parse({"result": None, "id": 1}) is None
    open_time = datetime(2026, 1, 1, tzinfo=UTC)
    assert parse(_message(open_time, closed=False)) is None
    with pytest.raises(DataIngestionError, match="not a valid Decimal"):
        parse(_message(open_time, open_value="not-a-decimal"))
    assert _CountingDateTime.calls == 0

    first = parse(_message(open_time))
    second = parse(_message(open_time + DURATION))

    assert first is not None
    assert second is not None
    assert _CountingDateTime.calls == 2
    assert first.received_at == datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
    assert second.received_at == datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC)


@pytest.mark.asyncio
async def test_provider_close_timestamp_mismatch_interrupts_before_emit() -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients)
    stream, next_item, client = await _start_stream(manager, clients)
    client.emit(_message(_current_anchor(), close_adjust_ms=1))

    with pytest.raises(LiveStreamInterrupted) as raised:
        await next_item
    assert raised.value.reason == "websocket_malformed_payload"
    assert client.stop_calls == 1
    await stream.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malformed_kind",
    [
        "invalid_json",
        "unknown_symbol",
        "wrong_interval",
        "bad_decimal",
        "bad_timestamp",
        "bad_close_flag",
        "missing_close_flag",
    ],
)
async def test_malformed_live_payload_interrupts(
    malformed_kind: str,
) -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients)
    stream, next_item, client = await _start_stream(manager, clients)
    open_time = _current_anchor()

    if malformed_kind == "invalid_json":
        client.emit("{")
    else:
        message = _message(
            open_time,
            symbol="UNKNOWN" if malformed_kind == "unknown_symbol" else SYMBOL,
            interval="5m" if malformed_kind == "wrong_interval" else "1m",
            open_value="not-a-decimal" if malformed_kind == "bad_decimal" else "100.0",
            closed="true" if malformed_kind == "bad_close_flag" else True,
            include_close_flag=malformed_kind != "missing_close_flag",
        )
        if malformed_kind == "bad_timestamp":
            message["data"]["k"]["t"] = "not-a-timestamp"
        client.emit(message)

    with pytest.raises(LiveStreamInterrupted) as raised:
        await next_item
    assert raised.value.reason == "websocket_malformed_payload"
    assert client.stop_calls == 1
    await stream.aclose()


@pytest.mark.asyncio
async def test_stale_finalized_candle_is_ignored_before_first_progress() -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients)
    stream, next_item, client = await _start_stream(manager, clients)
    open_time = _current_anchor()

    client.emit(_message(open_time - DURATION))
    await asyncio.sleep(0)
    assert not next_item.done()
    client.emit(_message(open_time))
    observation = await next_item
    assert observation.open_time == open_time
    await stream.aclose()


@pytest.mark.asyncio
async def test_exact_duplicate_finalized_candle_is_ignored() -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients)
    stream, next_item, client = await _start_stream(manager, clients)
    open_time = _current_anchor()
    first = await _emit_and_receive(client, next_item, _message(open_time))

    next_item = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0)
    client.emit(_message(open_time))
    await asyncio.sleep(0)
    assert not next_item.done()
    client.emit(_message(open_time + DURATION))
    second = await next_item

    assert first.open_time == open_time
    assert second.open_time == open_time + DURATION
    await stream.aclose()


@pytest.mark.asyncio
async def test_live_gap_interrupts_without_emitting_later_candle() -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients)
    stream, next_item, client = await _start_stream(manager, clients)
    open_time = _current_anchor()
    await _emit_and_receive(client, next_item, _message(open_time))

    next_item = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0)
    client.emit(_message(open_time + 2 * DURATION))

    with pytest.raises(LiveStreamInterrupted) as raised:
        await next_item
    assert raised.value.reason == "websocket_gap_detected"
    await stream.aclose()


@pytest.mark.asyncio
async def test_explicit_anchor_is_used_and_later_candle_triggers_gap() -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients)
    connection_anchor = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    stream, next_item, client = await _start_stream(
        manager,
        clients,
        connection_anchor=connection_anchor,
    )

    first = await _emit_and_receive(
        client,
        next_item,
        _message(connection_anchor),
    )
    assert first.open_time == connection_anchor

    next_item = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0)
    client.emit(_message(connection_anchor + 2 * DURATION))

    with pytest.raises(LiveStreamInterrupted) as raised:
        await next_item
    assert raised.value.reason == "websocket_gap_detected"
    await stream.aclose()


@pytest.mark.asyncio
async def test_queue_overflow_interrupts_without_dropping_oldest() -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients, queue_maxsize=1)
    stream, next_item, client = await _start_stream(manager, clients)
    open_time = _current_anchor()
    await _emit_and_receive(client, next_item, _message(open_time))

    next_item = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0)
    client.emit(_message(open_time + DURATION))
    client.emit(_message(open_time + 2 * DURATION))

    with pytest.raises(LiveStreamInterrupted) as raised:
        await next_item
    assert raised.value.reason == "websocket_queue_overflow"
    await stream.aclose()


@pytest.mark.asyncio
async def test_disconnect_wakes_consumer_waiting_on_empty_queue() -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients)
    stream, next_item, client = await _start_stream(manager, clients)
    client.close()

    with pytest.raises(LiveStreamInterrupted) as raised:
        await next_item
    assert raised.value.reason == "websocket_disconnected"
    await stream.aclose()
    assert client.stop_calls == 1


@pytest.mark.asyncio
async def test_error_callback_interrupts_and_cleans_up() -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients)
    stream, next_item, client = await _start_stream(manager, clients)
    client.error(RuntimeError("socket failed"))

    with pytest.raises(LiveStreamInterrupted) as raised:
        await next_item
    assert raised.value.reason == "websocket_error"
    assert client.stop_calls == 1
    await stream.aclose()


@pytest.mark.asyncio
async def test_callback_from_thread_bridges_into_async_consumer() -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients)
    stream, next_item, client = await _start_stream(manager, clients)
    thread = threading.Thread(
        target=client.emit_from_thread,
        args=(_message(_current_anchor()),),
    )
    thread.start()
    await asyncio.to_thread(thread.join)
    observation = await next_item

    assert observation.transport == "websocket"
    await stream.aclose()


@pytest.mark.asyncio
async def test_thread_callback_burst_schedules_one_bounded_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients, queue_maxsize=1)
    stream, next_item, client = await _start_stream(manager, clients)
    open_time = _current_anchor()
    loop = asyncio.get_running_loop()
    scheduled: list[object] = []
    original_call_soon_threadsafe = loop.call_soon_threadsafe

    def count_scheduled(callback: object, *args: object) -> None:
        scheduled.append(callback)
        original_call_soon_threadsafe(callback, *args)

    monkeypatch.setattr(loop, "call_soon_threadsafe", count_scheduled)

    def emit_burst() -> None:
        for _ in range(1_000):
            client.emit_from_thread(_message(open_time, closed=False))
        client.emit_from_thread(_message(open_time))
        client.emit_from_thread(_message(open_time + DURATION))

    thread = threading.Thread(target=emit_burst)
    thread.start()
    thread.join()

    assert len(scheduled) == 1
    with pytest.raises(LiveStreamInterrupted) as raised:
        await next_item
    assert raised.value.reason == "websocket_queue_overflow"
    await stream.aclose()
    assert client.stop_calls == 1


def test_cancelled_factory_stops_client_after_event_loop_shutdown() -> None:
    factory_started = threading.Event()
    release_factory = threading.Event()
    stopped = threading.Event()
    clients: list[_FakeClient] = []
    factory_calls: list[None] = []

    class _ShutdownClient(_FakeClient):
        def stop(self) -> None:
            super().stop()
            stopped.set()

    def factory(**kwargs: Any) -> _ShutdownClient:
        factory_calls.append(None)
        factory_started.set()
        release_factory.wait(5)
        client = _ShutdownClient(**kwargs)
        clients.append(client)
        return client

    manager = BinanceWebSocketManager(
        stream_url="wss://example.test",
        queue_maxsize=1,
        client_factory=factory,
    )

    async def cancel_stream() -> None:
        stream = manager.stream_closed_candles(
            {LANE: SYMBOL},
            base_timeframe="1m",
            timeframe_duration=DURATION,
            alignment_origin=ORIGIN,
            connection_anchor=_current_anchor(),
        )
        next_item = asyncio.create_task(stream.__anext__())
        assert await asyncio.to_thread(factory_started.wait, 5)
        next_item.cancel()
        with pytest.raises(asyncio.CancelledError):
            await next_item

    asyncio.run(cancel_stream())
    assert len(factory_calls) == 1

    release_factory.set()
    assert stopped.wait(5)
    assert clients[0].stop_calls == 1


@pytest.mark.asyncio
async def test_abandoned_factory_construction_has_one_inflight_admission() -> None:
    factory_started = threading.Event()
    release_factory = threading.Event()
    stopped = threading.Event()
    factory_calls: list[None] = []
    clients: list[_FakeClient] = []

    class _HeldClient(_FakeClient):
        def stop(self) -> None:
            super().stop()
            stopped.set()

    def factory(**kwargs: Any) -> _HeldClient:
        factory_calls.append(None)
        factory_started.set()
        release_factory.wait(5)
        client = _HeldClient(**kwargs)
        clients.append(client)
        return client

    manager = BinanceWebSocketManager(
        stream_url="wss://example.test",
        queue_maxsize=1,
        client_factory=factory,
    )
    first_stream = manager.stream_closed_candles(
        {LANE: SYMBOL},
        base_timeframe="1m",
        timeframe_duration=DURATION,
        alignment_origin=ORIGIN,
        connection_anchor=_current_anchor(),
    )
    first_item = asyncio.create_task(first_stream.__anext__())
    assert await asyncio.to_thread(factory_started.wait, 5)
    first_item.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_item

    second_stream = manager.stream_closed_candles(
        {LANE: SYMBOL},
        base_timeframe="1m",
        timeframe_duration=DURATION,
        alignment_origin=ORIGIN,
        connection_anchor=_current_anchor(),
    )
    second_item = asyncio.create_task(second_stream.__anext__())
    with pytest.raises(LiveStreamInterrupted) as raised:
        await second_item
    assert raised.value.reason == "connection_lifecycle_busy"
    assert len(factory_calls) == 1

    release_factory.set()
    assert await asyncio.to_thread(stopped.wait, 5)
    assert clients[0].stop_calls == 1
    await first_stream.aclose()
    await second_stream.aclose()


@pytest.mark.asyncio
async def test_cancelled_subscription_and_hung_stop_block_reopen() -> None:
    subscription_started = threading.Event()
    release_subscription = threading.Event()
    stop_started = threading.Event()
    release_stop = threading.Event()
    stop_finished = threading.Event()
    factory_calls: list[None] = []
    clients: list[_FakeClient] = []

    class _HeldLifecycleClient(_FakeClient):
        def subscribe(self, streams: list[str]) -> None:
            subscription_started.set()
            release_subscription.wait(5)
            super().subscribe(streams)

        def stop(self) -> None:
            stop_started.set()
            release_stop.wait(5)
            super().stop()
            stop_finished.set()

    def factory(**kwargs: Any) -> _FakeClient:
        factory_calls.append(None)
        client = (
            _HeldLifecycleClient(**kwargs)
            if len(factory_calls) == 1
            else _FakeClient(**kwargs)
        )
        clients.append(client)
        return client

    manager = BinanceWebSocketManager(
        stream_url="wss://example.test",
        queue_maxsize=1,
        client_factory=factory,
    )
    first_stream = manager.stream_closed_candles(
        {LANE: SYMBOL},
        base_timeframe="1m",
        timeframe_duration=DURATION,
        alignment_origin=ORIGIN,
        connection_anchor=_current_anchor(),
    )
    first_item = asyncio.create_task(first_stream.__anext__())
    assert await asyncio.to_thread(subscription_started.wait, 5)
    first_item.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_item

    second_stream = manager.stream_closed_candles(
        {LANE: SYMBOL},
        base_timeframe="1m",
        timeframe_duration=DURATION,
        alignment_origin=ORIGIN,
        connection_anchor=_current_anchor(),
    )
    second_item = asyncio.create_task(second_stream.__anext__())
    with pytest.raises(LiveStreamInterrupted) as raised:
        await second_item
    assert raised.value.reason == "connection_lifecycle_busy"
    assert len(factory_calls) == 1

    release_subscription.set()
    assert await asyncio.to_thread(stop_started.wait, 5)

    third_stream = manager.stream_closed_candles(
        {LANE: SYMBOL},
        base_timeframe="1m",
        timeframe_duration=DURATION,
        alignment_origin=ORIGIN,
        connection_anchor=_current_anchor(),
    )
    third_item = asyncio.create_task(third_stream.__anext__())
    with pytest.raises(LiveStreamInterrupted) as raised:
        await third_item
    assert raised.value.reason == "connection_lifecycle_busy"
    assert len(factory_calls) == 1

    release_stop.set()
    assert await asyncio.to_thread(stop_finished.wait, 5)
    assert clients[0].stop_calls == 1
    await first_stream.aclose()
    await second_stream.aclose()
    await third_stream.aclose()


@pytest.mark.asyncio
async def test_cancellation_propagates_and_stops_client_once() -> None:
    clients: list[_FakeClient] = []
    manager = _manager(clients)
    stream, next_item, client = await _start_stream(manager, clients)
    next_item.cancel()

    with pytest.raises(asyncio.CancelledError):
        await next_item
    await asyncio.sleep(0)
    assert client.stop_calls == 1
    await stream.aclose()


@pytest.mark.asyncio
async def test_stop_exception_completes_ownership_and_quarantines_reopen() -> None:
    clients: list[_FakeClient] = []
    stop_calls: list[None] = []

    class _FailingStopClient(_FakeClient):
        def stop(self) -> None:
            super().stop()
            stop_calls.append(None)
            raise RuntimeError("synthetic stop failure")

    def factory(**kwargs: Any) -> _FakeClient:
        client = _FailingStopClient(**kwargs) if not clients else _FakeClient(**kwargs)
        clients.append(client)
        return client

    manager = BinanceWebSocketManager(
        stream_url="wss://example.test",
        queue_maxsize=1,
        client_factory=factory,
    )
    stream, next_item, client = await _start_stream(manager, clients)
    next_item.cancel()
    with pytest.raises(asyncio.CancelledError):
        await next_item
    assert client.stop_calls == 1
    assert len(stop_calls) == 1
    for _ in range(100):
        if manager._lifecycle_quarantined:
            break
        await asyncio.sleep(0)
    assert manager._lifecycle_quarantined is True
    assert manager._lifecycle_active is False

    reopened = manager.stream_closed_candles(
        {LANE: SYMBOL},
        base_timeframe="1m",
        timeframe_duration=DURATION,
        alignment_origin=ORIGIN,
        connection_anchor=_current_anchor(),
    )
    reopened_item = asyncio.create_task(reopened.__anext__())
    with pytest.raises(DataIngestionError) as raised:
        await reopened_item
    assert raised.value.message == (
        "Binance websocket lifecycle cleanup failed; lifecycle quarantined"
    )
    await stream.aclose()
    await reopened.aclose()
    assert len(clients) == 1


async def _emit_and_receive(
    client: _FakeClient,
    next_item: asyncio.Task[Any],
    message: object,
) -> Any:
    client.emit(message)
    return await next_item
