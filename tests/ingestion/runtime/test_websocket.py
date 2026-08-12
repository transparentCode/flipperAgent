from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.providers.base import (
    LiveCandleProvider,
    LiveStreamInterrupted,
)
from apps.ingestion_app.runtime.websocket import (
    BinanceWebSocketManager,
    _build_recovery_requests,
)
from apps.ingestion_app.services.time_alignment import aligned_bucket_start

ORIGIN = datetime(1970, 1, 5, tzinfo=UTC)
DURATION = timedelta(minutes=1)
LANE = MarketLane("binance", "BTC-TEST-PERP", "1m")
SYMBOL = "BTCUSDT"


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
        "v": "10.0",
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
) -> BinanceWebSocketManager:
    def factory(**kwargs: Any) -> _FakeClient:
        client = _FakeClient(**kwargs)
        clients.append(client)
        return client

    return BinanceWebSocketManager(
        stream_url="wss://example.test",
        queue_maxsize=queue_maxsize,
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
    for _ in range(3):
        await asyncio.sleep(0)
    assert clients
    return stream, next_item, clients[0]


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
    assert observation.volume == Decimal("10.0")
    assert observation.taker_buy_base == Decimal("12.5")
    await stream.aclose()
    assert client.stop_calls == 1


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


async def _emit_and_receive(
    client: _FakeClient,
    next_item: asyncio.Task[Any],
    message: object,
) -> Any:
    client.emit(message)
    return await next_item
