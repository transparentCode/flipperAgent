"""Loss-safe multiplexed Binance websocket delivery for ingestion."""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime, timedelta
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
from apps.ingestion_app.runtime.websocket_bridge import (
    _BoundedCallbackBridge,
    _BridgeControl,
)
from apps.ingestion_app.runtime.websocket_sequence import LiveSequenceTracker
from apps.ingestion_app.runtime.websocket_session import (
    BinanceWebSocketSession,
    BinanceWebSocketSessionOwner,
)
from apps.ingestion_app.services.time_alignment import aligned_bucket_start
from libs.common.enums import SystemComponent
from libs.common.exceptions import DataIngestionError
from libs.common.logging.logger_utils import bind_logger

_LOGGER = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)
_WAKE_SENTINEL = object()


def _utc_now() -> datetime:
    """Return the UTC wall-clock sample used by causal live-stream checks."""
    return datetime.now(UTC)


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
        self._session_owner = BinanceWebSocketSessionOwner(
            stream_url=self.stream_url,
            lifecycle_timeout_seconds=self.lifecycle_timeout_seconds,
            client_factory=self.client_factory,
            provider_id=self.provider_id,
        )

    @property
    def lifecycle_quarantined(self) -> bool:
        return self._session_owner.lifecycle_quarantined

    @property
    def lifecycle_quarantine_error(self) -> DataIngestionError | None:
        return self._session_owner.lifecycle_quarantine_error

    @property
    def retained_worker_count(self) -> int:
        return self._session_owner.retained_worker_count

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
            received_at_fn=_utc_now,
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
        queue: asyncio.Queue[object] = asyncio.Queue(maxsize=self.queue_maxsize)
        callback_bridge = _BoundedCallbackBridge(self.queue_maxsize)
        tracker = LiveSequenceTracker(
            routes=routes,
            connection_anchor=connection_anchor,
            timeframe_duration=timeframe_duration,
            alignment_origin=alignment_origin,
        )
        failure: LiveStreamInterrupted | None = None
        intentional_stop = False
        stream_finished = False
        session: BinanceWebSocketSession | None = None

        def recovery_requests(
            reason: str,
            *,
            interruption_time: datetime | None = None,
        ) -> tuple[RecoveryRequest, ...]:
            return tracker.recovery_requests(
                reason,
                interruption_time=(
                    _utc_now() if interruption_time is None else interruption_time
                ),
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

        def interrupt(
            reason: str,
            detail: str | None = None,
            *,
            interruption_time: datetime | None = None,
        ) -> None:
            nonlocal failure
            if intentional_stop or stream_finished or failure is not None:
                return
            failure = LiveStreamInterrupted(
                reason=reason,
                recovery_requests=recovery_requests(
                    reason,
                    interruption_time=interruption_time,
                ),
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

        stream_names = sorted(
            f"{provider_symbol.lower()}@kline_{base_timeframe}"
            for _normalized_symbol, (_lane, provider_symbol) in routes.items()
        )

        try:
            session = self._session_owner.open(
                loop=loop,
                stream_names=stream_names,
                on_open=on_open,
                on_message=on_message,
                on_close=on_close,
                on_error=on_error,
            )
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

        try:
            try:
                await session.start()
                if self._ever_connected:
                    self.observability.record_websocket_reconnect()
                self._ever_connected = True
                self.observability.set_websocket_connected(True)
            except asyncio.CancelledError:
                session.abandon_pending_calls()
                raise
            except TransportDeadlineExceeded:
                session.abandon_pending_calls()
                raise
            except Exception as exc:  # noqa: BLE001 - SDK failures must become typed interruptions
                session.abandon_pending_calls()
                interrupt("websocket_error", str(exc))

            boundary_ready_items: int | None = None
            while True:
                if failure is not None:
                    raise failure

                overdue_lanes = tracker.overdue_silence_lanes(_utc_now())
                if overdue_lanes:
                    # A timeout and a callback-bridge drain can become ready in
                    # the same event-loop turn.  Observe the queue work that
                    # was already admitted at the boundary, but take one
                    # bounded snapshot so continuous unrelated traffic cannot
                    # postpone a genuinely silent lane forever.
                    if boundary_ready_items is None:
                        await asyncio.sleep(0)
                        if failure is not None:
                            raise failure
                        boundary_ready_items = queue.qsize()
                    if boundary_ready_items > 0:
                        item = queue.get_nowait()
                        boundary_ready_items -= 1
                    else:
                        watchdog_now = _utc_now()
                        still_overdue = tracker.overdue_silence_lanes(watchdog_now)
                        if still_overdue:
                            lane_text = ", ".join(
                                f"{lane.venue}/{lane.instrument_id}/{lane.timeframe}"
                                for lane in still_overdue
                            )
                            interrupt(
                                "websocket_silence_detected",
                                f"causal silence deadline exceeded for lanes: {lane_text}",
                                interruption_time=watchdog_now,
                            )
                            raise failure
                        boundary_ready_items = None
                        continue
                else:
                    boundary_ready_items = None
                    _earliest_lane, earliest_deadline = (
                        tracker.earliest_silence_deadline()
                    )
                    timeout_seconds = (earliest_deadline - _utc_now()).total_seconds()
                    if timeout_seconds <= 0:
                        continue
                    try:
                        async with asyncio.timeout(timeout_seconds):
                            item = await queue.get()
                    except TimeoutError:
                        continue
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

                decision = tracker.classify(observation)
                if decision.kind == "ignore":
                    continue
                if decision.kind == "interrupt":
                    interrupt(
                        decision.reason or "websocket_malformed_payload",
                        decision.detail,
                    )
                    raise failure

                yield observation
                tracker.record_consumed(observation)
        finally:
            stream_finished = True
            intentional_stop = True
            callback_bridge.close()
            self.observability.set_websocket_connected(False)
            self.observability.set_queue_utilization(
                queue.qsize(),
                self.queue_maxsize,
            )
            if session is not None:
                try:
                    await session.close()
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


__all__ = ["BinanceWebSocketManager"]
