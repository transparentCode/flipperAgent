from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from apps.ingestion_app.domain.candle import CandleObservation
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.runtime.websocket_bridge import (
    _BoundedCallbackBridge,
    _BridgeControl,
)
from apps.ingestion_app.runtime.websocket_sequence import (
    LiveSequenceTracker,
    SequenceDecision,
    _build_recovery_requests,
    _earliest_silence_deadline,
    _overdue_silence_lanes,
    _silence_deadline,
)
from apps.ingestion_app.runtime.websocket_session import (
    BinanceWebSocketSessionOwner,
)

ORIGIN = datetime(1970, 1, 5, tzinfo=UTC)
DURATION = timedelta(minutes=1)
ANCHOR = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
LANE = MarketLane("binance", "BTC-TEST-PERP", "1m")
SYMBOL = "BTCUSDT"


def _observation(
    open_time: datetime,
    *,
    lane: MarketLane = LANE,
    symbol: str = SYMBOL,
    duration: timedelta = DURATION,
) -> CandleObservation:
    return CandleObservation(
        lane=lane,
        provider_id="binance_native",
        provider_symbol=symbol,
        transport="websocket",
        open_time=open_time,
        close_time=open_time + duration,
        open=Decimal("100.0"),
        high=Decimal("101.0"),
        low=Decimal("99.0"),
        close=Decimal("100.5"),
        volume=Decimal("20.0"),
        taker_buy_base=Decimal("12.5"),
        received_at=open_time + timedelta(seconds=1),
        provider_close_time=open_time + duration,
    )


def test_bridge_is_bounded_fifo_and_uses_urgent_overflow_control() -> None:
    bridge = _BoundedCallbackBridge(2)
    overflow = _BridgeControl("websocket_queue_overflow", "full")

    assert bridge.offer("first", overflow_control=overflow) is True
    assert bridge.offer("second", overflow_control=overflow) is False
    assert bridge.offer("third", overflow_control=overflow) is False

    events, urgent = bridge.take_batch()
    assert events == ("first", "second")
    assert urgent == overflow

    assert bridge.offer("after-drain", overflow_control=overflow) is True
    assert bridge.take_batch() == (("after-drain",), None)


def test_bridge_close_rejects_callbacks_and_resets_schedule() -> None:
    bridge = _BoundedCallbackBridge(1)
    control = _BridgeControl("websocket_disconnected")

    assert bridge.offer("event", overflow_control=control) is True
    bridge.close()

    assert bridge.offer("late", overflow_control=control) is False
    assert bridge.take_batch() == ((), None)


def test_sequence_classification_does_not_advance_consumed_state() -> None:
    tracker = LiveSequenceTracker(
        routes={SYMBOL.casefold(): (LANE, SYMBOL)},
        connection_anchor=ANCHOR,
        timeframe_duration=DURATION,
        alignment_origin=ORIGIN,
    )
    first = _observation(ANCHOR)

    assert tracker.classify(first) == SequenceDecision(kind="deliver")
    assert tracker.last_consumed_close == {}
    assert tracker.last_consumed_observation == {}

    tracker.record_consumed(first)
    assert tracker.last_consumed_close == {LANE: ANCHOR + DURATION}
    assert tracker.classify(first) == SequenceDecision(kind="ignore")
    assert tracker.classify(_observation(ANCHOR + 2 * DURATION)).reason == (
        "websocket_gap_detected"
    )
    assert tracker.classify(_observation(ANCHOR - DURATION)).reason == (
        "websocket_malformed_payload"
    )


def test_sequence_deadlines_and_recovery_are_deterministic_and_per_lane() -> None:
    lane_a = MarketLane("binance", "AAA-TEST-PERP", "1m")
    lane_b = MarketLane("binance", "BBB-TEST-PERP", "1m")
    routes = {
        "bbbusdt": (lane_b, "BBBUSDT"),
        "aaausdt": (lane_a, "AAAUSDT"),
    }
    progressed_a = ANCHOR + 10 * DURATION

    assert (
        _silence_deadline(
            last_consumed_close=None,
            connection_anchor=ANCHOR,
            timeframe_duration=DURATION,
        )
        == ANCHOR + 2 * DURATION
    )
    assert _earliest_silence_deadline(
        routes=routes,
        last_consumed_close={lane_a: progressed_a},
        connection_anchor=ANCHOR,
        timeframe_duration=DURATION,
    ) == (lane_b, ANCHOR + 2 * DURATION)
    assert _overdue_silence_lanes(
        routes=routes,
        last_consumed_close={},
        connection_anchor=ANCHOR,
        timeframe_duration=DURATION,
        now=ANCHOR + 2 * DURATION,
    ) == (lane_a, lane_b)

    requests = _build_recovery_requests(
        routes=routes,
        last_consumed_close={},
        connection_anchor=ANCHOR,
        interruption_time=ANCHOR + timedelta(minutes=3, seconds=10),
        timeframe_duration=DURATION,
        alignment_origin=ORIGIN,
        reason="websocket_silence_detected",
    )
    assert [request.lane for request in requests] == [lane_a, lane_b]
    assert all(request.since == ANCHOR for request in requests)


@pytest.mark.asyncio
async def test_session_owner_opens_one_batch_and_stops_once() -> None:
    clients: list[_SessionClient] = []

    def factory(**kwargs: Any) -> _SessionClient:
        client = _SessionClient(**kwargs)
        clients.append(client)
        return client

    owner = BinanceWebSocketSessionOwner(
        stream_url="wss://example.test",
        lifecycle_timeout_seconds=0.25,
        client_factory=factory,
        provider_id="binance_native",
    )
    callbacks = {
        "on_open": lambda *_args: None,
        "on_message": lambda *_args: None,
        "on_close": lambda *_args: None,
        "on_error": lambda *_args: None,
    }
    session = owner.open(
        loop=asyncio.get_running_loop(),
        stream_names=["btcusdt@kline_1m", "ethusdt@kline_1m"],
        **callbacks,
    )

    await session.start()
    await session.close()
    await session.close()

    assert len(clients) == 1
    assert clients[0].subscribe_calls == [["btcusdt@kline_1m", "ethusdt@kline_1m"]]
    assert clients[0].stop_calls == 1
    for _ in range(100):
        if owner.retained_worker_count == 0:
            break
        await asyncio.sleep(0)
    assert owner.retained_worker_count == 0
    assert owner.lifecycle_quarantined is False


class _SessionClient:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.subscribe_calls: list[list[str]] = []
        self.stop_calls = 0

    def subscribe(self, streams: list[str]) -> None:
        self.subscribe_calls.append(list(streams))

    def stop(self) -> None:
        self.stop_calls += 1
