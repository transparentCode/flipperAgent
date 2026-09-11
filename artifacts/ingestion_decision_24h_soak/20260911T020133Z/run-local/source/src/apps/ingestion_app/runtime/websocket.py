"""Loss-safe multiplexed Binance websocket delivery for ingestion."""

from __future__ import annotations

import asyncio
import math
from collections import deque
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

from apps.ingestion_app.domain.candle import CandleObservation
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.observability import IngestionObservability
from apps.ingestion_app.providers.base import (
    LiveStreamInterrupted,
    TransportDeadlineExceeded,
)
from apps.ingestion_app.runtime.binance_websocket_decode import (
    decode_binance_websocket_message,
)
from apps.ingestion_app.runtime.blocking import _OwnedBlockingCall, _OwnedCallTimeout
from apps.ingestion_app.services.time_alignment import aligned_bucket_start
from libs.common.enums import SystemComponent
from libs.common.exceptions import DataIngestionError
from libs.common.logging.logger_utils import bind_logger

_LOGGER = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)
_WAKE_SENTINEL = object()


@dataclass(frozen=True, slots=True)
class _BridgeControl:
    reason: str
    detail: str | None = None


class _ExactlyOnceStop:
    """Serialize all stop paths for one SDK client."""

    def __init__(self) -> None:
        self._client: Any | None = None
        self._lock = Lock()
        self._started = False

    def bind(self, client: Any) -> None:
        with self._lock:
            if self._client is None:
                self._client = client
                return
            if self._client is not client:
                raise RuntimeError("stop controller was bound to multiple clients")

    def run(self, client: Any | None = None) -> None:
        with self._lock:
            if client is not None:
                if self._client is None:
                    self._client = client
                elif self._client is not client:
                    raise RuntimeError("stop controller was bound to multiple clients")
            if self._started:
                return
            if self._client is None:
                return
            self._started = True
            client_to_stop = self._client
        client_to_stop.stop()


class _LifecycleLease:
    """Release one manager connection slot at most once."""

    def __init__(self, release: Callable[[], None]) -> None:
        self._release = release
        self._lock = Lock()
        self._released = False

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._release()


class _BoundedCallbackBridge:
    """Admit SDK callbacks before they can enter the event-loop ready queue."""

    def __init__(self, maxsize: int) -> None:
        self._maxsize = maxsize
        self._events: deque[object] = deque()
        self._urgent_control: _BridgeControl | None = None
        self._lock = Lock()
        self._drain_scheduled = False
        self._closed = False

    def offer(
        self,
        event: object,
        *,
        overflow_control: _BridgeControl,
    ) -> bool:
        """Admit one event and return whether a drain callback is needed."""
        with self._lock:
            if self._closed:
                return False
            if len(self._events) < self._maxsize:
                self._events.append(event)
            elif self._urgent_control is None:
                self._urgent_control = overflow_control

            if self._drain_scheduled:
                return False
            self._drain_scheduled = True
            return True

    def take_batch(self) -> tuple[tuple[object, ...], _BridgeControl | None]:
        with self._lock:
            events = tuple(self._events)
            self._events.clear()
            urgent_control = self._urgent_control
            self._urgent_control = None
            self._drain_scheduled = False
            return events, urgent_control

    def cancel_scheduled_drain(self) -> None:
        with self._lock:
            self._drain_scheduled = False

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._events.clear()
            self._urgent_control = None


def _require_non_empty_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _require_utc(value: object, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


def _require_positive_duration(value: object, *, field_name: str) -> timedelta:
    if not isinstance(value, timedelta):
        raise TypeError(f"{field_name} must be a timedelta")
    if value <= timedelta(0):
        raise ValueError(f"{field_name} must be positive")
    return value


def _require_queue_maxsize(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("queue_maxsize must be an integer")
    if value <= 0:
        raise ValueError("queue_maxsize must be positive")
    return value


def _require_positive_seconds(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    if not math.isfinite(float(value)) or value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return float(value)


def _same_live_observation(
    first: CandleObservation,
    second: CandleObservation,
) -> bool:
    return (
        first.lane == second.lane
        and first.provider_id == second.provider_id
        and first.provider_symbol == second.provider_symbol
        and first.transport == second.transport
        and first.open_time == second.open_time
        and first.close_time == second.close_time
        and first.open == second.open
        and first.high == second.high
        and first.low == second.low
        and first.close == second.close
        and first.volume == second.volume
        and first.taker_buy_base == second.taker_buy_base
        and first.provider_close_time == second.provider_close_time
        and first.provider_event_id == second.provider_event_id
    )


def _build_recovery_requests(
    *,
    routes: Mapping[str, tuple[MarketLane, str]],
    last_consumed_close: Mapping[MarketLane, datetime],
    connection_anchor: datetime,
    interruption_time: datetime,
    timeframe_duration: timedelta,
    alignment_origin: datetime,
    reason: str,
) -> tuple[RecoveryRequest, ...]:
    recovery_until = aligned_bucket_start(
        interruption_time,
        timeframe_duration,
        alignment_origin,
    )
    requests: list[RecoveryRequest] = []
    ordered_routes = sorted(
        routes.values(),
        key=lambda route: (
            route[0].venue,
            route[0].instrument_id,
            route[0].timeframe,
        ),
    )
    for lane, _provider_symbol in ordered_routes:
        recovery_since = last_consumed_close.get(lane, connection_anchor)
        if recovery_since < recovery_until:
            requests.append(
                RecoveryRequest(
                    lane=lane,
                    since=recovery_since,
                    until=recovery_until,
                    reason=reason,
                )
            )
    return tuple(requests)


class BinanceWebSocketManager:
    """Own one multiplexed Binance websocket and deliver closed candles."""

    provider_id = "binance_native"

    def __init__(
        self,
        *,
        stream_url: str,
        queue_maxsize: int,
        lifecycle_timeout_seconds: float = 30,
        client_factory: Callable[..., Any] = UMFuturesWebsocketClient,
        observability: IngestionObservability | None = None,
    ) -> None:
        stream_url = _require_non_empty_string(stream_url, field_name="stream_url")
        if not stream_url.startswith("wss://"):
            raise ValueError("stream_url must use wss://")
        if not callable(client_factory):
            raise TypeError("client_factory must be callable")
        self.stream_url = stream_url
        self.queue_maxsize = _require_queue_maxsize(queue_maxsize)
        self.lifecycle_timeout_seconds = _require_positive_seconds(
            lifecycle_timeout_seconds,
            field_name="lifecycle_timeout_seconds",
        )
        self.client_factory = client_factory
        self.observability = observability or IngestionObservability()
        self._ever_connected = False
        self._lifecycle_lock = Lock()
        self._lifecycle_active = False
        self._lifecycle_quarantined = False
        self._lifecycle_quarantine_error: DataIngestionError | None = None
        self._owned_calls: set[_OwnedBlockingCall] = set()

    @property
    def lifecycle_quarantined(self) -> bool:
        with self._lifecycle_lock:
            return self._lifecycle_quarantined

    @property
    def lifecycle_quarantine_error(self) -> DataIngestionError | None:
        with self._lifecycle_lock:
            return self._lifecycle_quarantine_error

    @property
    def retained_worker_count(self) -> int:
        with self._lifecycle_lock:
            return sum(not call.finished for call in self._owned_calls)

    def _track_call(self, call: _OwnedBlockingCall) -> None:
        with self._lifecycle_lock:
            self._owned_calls.add(call)

    def _forget_call(self, call: _OwnedBlockingCall) -> None:
        with self._lifecycle_lock:
            self._owned_calls.discard(call)

    def _acquire_lifecycle(self) -> _LifecycleLease:
        with self._lifecycle_lock:
            if self._lifecycle_quarantined:
                error = self._lifecycle_quarantine_error
                if error is None:
                    error = DataIngestionError(
                        "Binance websocket lifecycle is quarantined"
                    )
                raise error
            if self._lifecycle_active:
                raise RuntimeError(
                    "Binance websocket connection lifecycle is still outstanding"
                )
            self._lifecycle_active = True
        return _LifecycleLease(self._release_lifecycle)

    def _quarantine_lifecycle(
        self,
        error: DataIngestionError | None = None,
    ) -> None:
        with self._lifecycle_lock:
            self._lifecycle_quarantined = True
            if error is not None and self._lifecycle_quarantine_error is None:
                self._lifecycle_quarantine_error = error

    def _release_lifecycle(self) -> None:
        with self._lifecycle_lock:
            self._lifecycle_active = False

    def _start_client_construction(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        kwargs: Mapping[str, Any],
        abandoned_cleanup: Callable[[Any], None],
        finished_callback: Callable[[_OwnedBlockingCall], None],
    ) -> _OwnedBlockingCall:
        call = _OwnedBlockingCall(
            loop=loop,
            operation=lambda: self.client_factory(**kwargs),
            name="binance-websocket-factory",
            abandoned_cleanup=abandoned_cleanup,
            finished_callback=finished_callback,
        )
        self._track_call(call)
        call.start()
        return call

    @staticmethod
    def _validate_subscriptions(
        subscriptions: Mapping[MarketLane, str],
        *,
        base_timeframe: str,
        timeframe_duration: timedelta,
        alignment_origin: datetime,
        connection_anchor: datetime,
    ) -> dict[str, tuple[MarketLane, str]]:
        if not isinstance(subscriptions, Mapping):
            raise TypeError("subscriptions must be a mapping")
        if not subscriptions:
            raise ValueError("subscriptions must not be empty")
        _require_non_empty_string(base_timeframe, field_name="base_timeframe")
        _require_positive_duration(
            timeframe_duration,
            field_name="timeframe_duration",
        )
        _require_utc(alignment_origin, field_name="alignment_origin")
        _require_utc(connection_anchor, field_name="connection_anchor")
        if (
            aligned_bucket_start(
                connection_anchor,
                timeframe_duration,
                alignment_origin,
            )
            != connection_anchor
        ):
            raise ValueError("connection_anchor must align to the base grid")

        routes: dict[str, tuple[MarketLane, str]] = {}
        for lane, provider_symbol in subscriptions.items():
            if not isinstance(lane, MarketLane):
                raise TypeError("subscription keys must be MarketLane instances")
            if lane.timeframe != base_timeframe:
                raise ValueError(
                    f"live lane timeframe '{lane.timeframe}' must equal "
                    f"base_timeframe '{base_timeframe}'"
                )
            _require_non_empty_string(
                provider_symbol,
                field_name="provider_symbol",
            )
            normalized_symbol = provider_symbol.casefold()
            if normalized_symbol in routes:
                raise ValueError(
                    f"duplicate normalized provider symbol '{provider_symbol}'"
                )
            routes[normalized_symbol] = (lane, provider_symbol)
        return routes

    def stream_closed_candles(
        self,
        subscriptions: Mapping[MarketLane, str],
        *,
        base_timeframe: str,
        timeframe_duration: timedelta,
        alignment_origin: datetime,
        connection_anchor: datetime,
    ) -> AsyncIterator[CandleObservation]:
        routes = self._validate_subscriptions(
            subscriptions,
            base_timeframe=base_timeframe,
            timeframe_duration=timeframe_duration,
            alignment_origin=alignment_origin,
            connection_anchor=connection_anchor,
        )
        return self._stream_closed_candles(
            routes=routes,
            base_timeframe=base_timeframe,
            timeframe_duration=timeframe_duration,
            alignment_origin=alignment_origin,
            connection_anchor=connection_anchor,
        )

    def _parse_message(
        self,
        raw_message: object,
        *,
        routes: Mapping[str, tuple[MarketLane, str]],
        base_timeframe: str,
        timeframe_duration: timedelta,
        alignment_origin: datetime,
    ) -> CandleObservation | None:
        return decode_binance_websocket_message(
            raw_message,
            provider_id=self.provider_id,
            routes=routes,
            base_timeframe=base_timeframe,
            timeframe_duration=timeframe_duration,
            alignment_origin=alignment_origin,
            received_at_fn=lambda: datetime.now(UTC),
        )

    async def _stream_closed_candles(
        self,
        *,
        routes: Mapping[str, tuple[MarketLane, str]],
        base_timeframe: str,
        timeframe_duration: timedelta,
        alignment_origin: datetime,
        connection_anchor: datetime,
    ) -> AsyncIterator[CandleObservation]:
        loop = asyncio.get_running_loop()
        try:
            lifecycle = self._acquire_lifecycle()
        except RuntimeError as exc:
            reason = (
                "connection_lifecycle_quarantined"
                if "quarantined" in str(exc)
                else "connection_lifecycle_busy"
            )
            raise LiveStreamInterrupted(
                reason=reason,
                recovery_requests=(),
            ) from exc
        queue: asyncio.Queue[object] = asyncio.Queue(maxsize=self.queue_maxsize)
        callback_bridge = _BoundedCallbackBridge(self.queue_maxsize)
        last_consumed_close: dict[MarketLane, datetime] = {}
        last_consumed_observation: dict[MarketLane, CandleObservation] = {}
        failure: LiveStreamInterrupted | None = None
        intentional_stop = False
        stream_finished = False
        client: Any | None = None
        factory_call: _OwnedBlockingCall | None = None
        subscription_call: _OwnedBlockingCall | None = None
        stop_call: _OwnedBlockingCall | None = None
        stop_controller = _ExactlyOnceStop()

        def recovery_requests(reason: str) -> tuple[RecoveryRequest, ...]:
            return _build_recovery_requests(
                routes=routes,
                last_consumed_close=last_consumed_close,
                connection_anchor=connection_anchor,
                interruption_time=datetime.now(UTC),
                timeframe_duration=timeframe_duration,
                alignment_origin=alignment_origin,
                reason=reason,
            )

        def wake_consumer() -> None:
            try:
                queue.put_nowait(_WAKE_SENTINEL)
                self.observability.set_queue_utilization(
                    queue.qsize(),
                    self.queue_maxsize,
                )
            except asyncio.QueueFull:
                pass

        def interrupt(reason: str, detail: str | None = None) -> None:
            nonlocal failure
            if intentional_stop or stream_finished or failure is not None:
                return
            failure = LiveStreamInterrupted(
                reason=reason,
                recovery_requests=recovery_requests(reason),
            )
            self.observability.record_websocket_interruption()
            self.observability.set_websocket_connected(False)
            if detail:
                _LOGGER.warning(
                    "Binance live websocket interrupted: reason=%s detail=%s",
                    reason,
                    detail,
                )
            else:
                _LOGGER.warning(
                    "Binance live websocket interrupted: reason=%s",
                    reason,
                )
            wake_consumer()

        def request_bridge_drain() -> None:
            try:
                loop.call_soon_threadsafe(drain_callback_bridge)
            except RuntimeError:
                callback_bridge.cancel_scheduled_drain()

        def offer_bridge_event(
            event: object,
            *,
            overflow_control: _BridgeControl,
        ) -> None:
            if callback_bridge.offer(event, overflow_control=overflow_control):
                request_bridge_drain()

        def handle_message(raw_message: object) -> None:
            try:
                observation = self._parse_message(
                    raw_message,
                    routes=routes,
                    base_timeframe=base_timeframe,
                    timeframe_duration=timeframe_duration,
                    alignment_origin=alignment_origin,
                )
            except (
                DataIngestionError,
                KeyError,
                IndexError,
                OverflowError,
                TypeError,
                ValueError,
            ) as exc:
                control = _BridgeControl("websocket_malformed_payload", str(exc))
                offer_bridge_event(control, overflow_control=control)
                return
            if observation is None:
                return
            offer_bridge_event(
                observation,
                overflow_control=_BridgeControl(
                    "websocket_queue_overflow",
                    "finalized candle admission bridge is full",
                ),
            )

        def drain_callback_bridge() -> None:
            events, urgent_control = callback_bridge.take_batch()
            for event in events:
                if failure is not None or stream_finished:
                    return
                if isinstance(event, _BridgeControl):
                    interrupt(event.reason, event.detail)
                    return
                if not isinstance(event, CandleObservation):
                    interrupt(
                        "websocket_malformed_payload",
                        "callback bridge contained an invalid item",
                    )
                    return
                try:
                    queue.put_nowait(event)
                    self.observability.set_queue_utilization(
                        queue.qsize(),
                        self.queue_maxsize,
                    )
                except asyncio.QueueFull:
                    interrupt(
                        "websocket_queue_overflow",
                        "finalized candle queue is full",
                    )
                    return
            if urgent_control is not None and failure is None and not stream_finished:
                interrupt(urgent_control.reason, urgent_control.detail)

        def on_open(_websocket: object, *_args: object) -> None:
            return None

        def on_message(_websocket: object, raw_message: object) -> None:
            handle_message(raw_message)

        def on_close(_websocket: object, *_args: object) -> None:
            control = _BridgeControl("websocket_disconnected")
            offer_bridge_event(control, overflow_control=control)

        def on_error(_websocket: object, error: object, *_args: object) -> None:
            control = _BridgeControl("websocket_error", str(error))
            offer_bridge_event(control, overflow_control=control)

        def finish_abandoned_call(call: _OwnedBlockingCall) -> None:
            if not call.adopted:
                if call.cleanup_failed:
                    self._quarantine_lifecycle(
                        DataIngestionError(
                            "Binance websocket lifecycle cleanup failed; "
                            "lifecycle quarantined"
                        )
                    )
                lifecycle.release()
            self._forget_call(call)

        def finish_stop(call: _OwnedBlockingCall) -> None:
            if call.failed:
                self._quarantine_lifecycle(
                    DataIngestionError(
                        "Binance websocket lifecycle cleanup failed; "
                        "lifecycle quarantined"
                    )
                )
            lifecycle.release()
            self._forget_call(call)

        async def wait_for_lifecycle_call(
            call: _OwnedBlockingCall,
            *,
            operation: str,
            abandon_on_error: bool = True,
        ) -> Any:
            try:
                result = await call.wait(self.lifecycle_timeout_seconds)
            except _OwnedCallTimeout as exc:
                # A completion that won the race is known ownership; only an
                # operation still running at the deadline is fatal.
                if (
                    call.operation_finished
                    and call.operation_finished_at is not None
                    and call.operation_finished_at <= exc.deadline
                ):
                    try:
                        result = call.result_or_raise()
                    except BaseException:
                        if abandon_on_error:
                            # The call completed with a known error, so it is
                            # still eligible for the existing normal cleanup.
                            call.abandon()
                        else:
                            call.adopt()
                        raise
                    if not call.adopt():
                        raise asyncio.CancelledError
                    return result
                call.abandon()
                error = TransportDeadlineExceeded(
                    provider_id=self.provider_id,
                    operation=operation,
                    timeout_seconds=self.lifecycle_timeout_seconds,
                )
                self._quarantine_lifecycle(error)
                raise error from exc
            except asyncio.CancelledError:
                call.abandon()
                raise
            except BaseException:
                if abandon_on_error:
                    call.abandon()
                else:
                    call.adopt()
                raise
            if not call.adopt():
                raise asyncio.CancelledError
            return result

        def stop_client_with_bounded_reap(client_to_stop: Any) -> None:
            if client_to_stop is None:
                return
            stop_controller.bind(client_to_stop)
            try:
                stop_controller.run(client_to_stop)
            except BrokenPipeError:
                socket_manager = getattr(client_to_stop, "socket_manager", None)
                join = getattr(socket_manager, "join", None)
                is_alive = getattr(socket_manager, "is_alive", None)
                if not callable(join) or not callable(is_alive):
                    raise
                join(self.lifecycle_timeout_seconds)
                if is_alive():
                    raise RuntimeError(
                        "Binance websocket socket-manager thread did not terminate"
                    )

        async def stop_client_once(client_to_stop: Any) -> None:
            nonlocal stop_call

            if stop_call is None:
                stop_call = _OwnedBlockingCall(
                    loop=loop,
                    operation=lambda: stop_client_with_bounded_reap(client_to_stop),
                    name="binance-websocket-stop",
                    finished_callback=finish_stop,
                )
                self._track_call(stop_call)
                stop_call.start()
            await wait_for_lifecycle_call(
                stop_call,
                operation="websocket stop",
                abandon_on_error=False,
            )

        stream_names = sorted(
            f"{provider_symbol.lower()}@kline_{base_timeframe}"
            for _normalized_symbol, (_lane, provider_symbol) in routes.items()
        )

        try:
            try:
                factory_call = self._start_client_construction(
                    loop=loop,
                    kwargs={
                        "stream_url": self.stream_url,
                        "on_open": on_open,
                        "on_message": on_message,
                        "on_close": on_close,
                        "on_error": on_error,
                        "is_combined": True,
                    },
                    abandoned_cleanup=stop_client_with_bounded_reap,
                    finished_callback=finish_abandoned_call,
                )
                client = await wait_for_lifecycle_call(
                    factory_call,
                    operation="websocket factory",
                )
                stop_controller.bind(client)
                subscription_call = _OwnedBlockingCall(
                    loop=loop,
                    operation=lambda: client.subscribe(stream_names),
                    name="binance-websocket-subscribe",
                    abandoned_cleanup=lambda _result: stop_client_with_bounded_reap(
                        client
                    ),
                    finished_callback=finish_abandoned_call,
                )
                self._track_call(subscription_call)
                subscription_call.start()
                await wait_for_lifecycle_call(
                    subscription_call,
                    operation="websocket subscribe",
                )
                if self._ever_connected:
                    self.observability.record_websocket_reconnect()
                self._ever_connected = True
                self.observability.set_websocket_connected(True)
            except asyncio.CancelledError:
                if subscription_call is not None and not subscription_call.adopted:
                    subscription_call.abandon()
                if factory_call is not None and not factory_call.adopted:
                    factory_call.abandon()
                raise
            except TransportDeadlineExceeded:
                if subscription_call is not None and not subscription_call.adopted:
                    subscription_call.abandon()
                if factory_call is not None and not factory_call.adopted:
                    factory_call.abandon()
                raise
            except Exception as exc:  # noqa: BLE001 - SDK failures must become typed interruptions
                if subscription_call is not None and not subscription_call.adopted:
                    subscription_call.abandon()
                if factory_call is not None and not factory_call.adopted:
                    factory_call.abandon()
                interrupt("websocket_error", str(exc))

            while True:
                if failure is not None:
                    raise failure
                item = await queue.get()
                self.observability.set_queue_utilization(
                    queue.qsize(),
                    self.queue_maxsize,
                )
                if failure is not None:
                    raise failure
                if item is _WAKE_SENTINEL:
                    continue

                observation = item
                if not isinstance(observation, CandleObservation):
                    interrupt(
                        "websocket_malformed_payload",
                        "internal queue contained an invalid item",
                    )
                    raise failure

                previous = last_consumed_observation.get(observation.lane)
                if previous is None:
                    if observation.close_time <= connection_anchor:
                        continue
                    if observation.open_time < connection_anchor:
                        interrupt(
                            "websocket_malformed_payload",
                            "older out-of-order candle preceded live progress",
                        )
                        raise failure
                    if observation.open_time != connection_anchor:
                        interrupt(
                            "websocket_gap_detected",
                            "first live candle did not begin at the connection anchor",
                        )
                        raise failure
                elif _same_live_observation(observation, previous):
                    continue
                elif observation.open_time < previous.close_time:
                    interrupt(
                        "websocket_malformed_payload",
                        "older out-of-order finalized candle received",
                    )
                    raise failure
                elif observation.open_time > previous.close_time:
                    interrupt(
                        "websocket_gap_detected",
                        "finalized live candle gap detected",
                    )
                    raise failure

                yield observation
                last_consumed_close[observation.lane] = observation.close_time
                last_consumed_observation[observation.lane] = observation
        finally:
            stream_finished = True
            intentional_stop = True
            callback_bridge.close()
            self.observability.set_websocket_connected(False)
            self.observability.set_queue_utilization(
                queue.qsize(),
                self.queue_maxsize,
            )
            if subscription_call is not None and not subscription_call.adopted:
                subscription_call.abandon()
            if factory_call is not None and not factory_call.adopted:
                factory_call.abandon()
            construction_still_owns_client = any(
                call is not None and not call.adopted and not call.finished
                for call in (factory_call, subscription_call)
            )
            if client is not None and not construction_still_owns_client:
                try:
                    await stop_client_once(client)
                except asyncio.CancelledError:
                    raise
                except TransportDeadlineExceeded:
                    # A stop worker still owned by its SDK at the deadline is
                    # a fatal lifecycle state; do not turn it into a log-only
                    # cleanup failure.
                    raise
                except Exception as exc:  # noqa: BLE001 - cleanup must not mask stream outcome
                    _LOGGER.warning(
                        "Binance live websocket cleanup failed: %s",
                        exc,
                    )
            elif client is None and factory_call is None:
                lifecycle.release()


__all__ = ["BinanceWebSocketManager"]
