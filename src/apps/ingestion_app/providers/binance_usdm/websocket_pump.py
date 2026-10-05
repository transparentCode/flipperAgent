"""Connection-scoped closed-candle pump for one multiplexed Binance websocket."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import datetime, timedelta
from typing import NoReturn

from apps.ingestion_app.domain.candle import CandleObservation
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.observability import IngestionObservability
from apps.ingestion_app.providers.base import (
    LiveStreamInterrupted,
    TransportDeadlineExceeded,
)
from apps.ingestion_app.providers.live_sequence import LiveSequenceTracker
from libs.common.enums import SystemComponent
from libs.common.exceptions import DataIngestionError
from libs.common.logging.logger_utils import bind_logger

from .websocket_bridge import _BoundedCallbackBridge, _BridgeControl
from .websocket_session import (
    BinanceWebSocketSession,
    BinanceWebSocketSessionOwner,
)

_LOGGER = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)
_WAKE_SENTINEL = object()


class _ClosedCandlePump:
    """Own all ephemeral state for one multiplexed websocket connection."""

    def __init__(
        self,
        *,
        routes: Mapping[str, tuple[MarketLane, str]],
        base_timeframe: str,
        timeframe_duration: timedelta,
        alignment_origin: datetime,
        connection_anchor: datetime,
        queue_maxsize: int,
        observability: IngestionObservability,
        session_owner: BinanceWebSocketSessionOwner,
        parse_message: Callable[..., CandleObservation | None],
        on_connection_started: Callable[[], None],
        tracker_factory: Callable[..., LiveSequenceTracker],
        now_fn: Callable[[], datetime],
    ) -> None:
        self._routes = routes
        self._base_timeframe = base_timeframe
        self._timeframe_duration = timeframe_duration
        self._alignment_origin = alignment_origin
        self._queue_maxsize = queue_maxsize
        self._observability = observability
        self._session_owner = session_owner
        self._parse_message = parse_message
        self._on_connection_started = on_connection_started
        self._now_fn = now_fn

        self._queue: asyncio.Queue[object] = asyncio.Queue(maxsize=queue_maxsize)
        self._callback_bridge = _BoundedCallbackBridge(queue_maxsize)
        self._tracker = tracker_factory(
            routes=routes,
            connection_anchor=connection_anchor,
            timeframe_duration=timeframe_duration,
            alignment_origin=alignment_origin,
        )
        # The stream may be created outside a running loop and first iterated
        # inside one, so only ``run`` obtains the loop.
        self._loop: asyncio.AbstractEventLoop
        self._failure: LiveStreamInterrupted | None = None
        self._intentional_stop = False
        self._stream_finished = False
        self._session: BinanceWebSocketSession | None = None

    async def run(self) -> AsyncIterator[CandleObservation]:
        """Start, consume, and clean up one connection-scoped stream."""
        self._loop = asyncio.get_running_loop()
        tracker = self._tracker
        queue = self._queue
        session = self._open_session()
        self._session = session

        try:
            try:
                await session.start()
                self._on_connection_started()
            except asyncio.CancelledError:
                session.abandon_pending_calls()
                raise
            except TransportDeadlineExceeded:
                session.abandon_pending_calls()
                raise
            except Exception as exc:  # noqa: BLE001 - SDK failures must become typed interruptions
                session.abandon_pending_calls()
                self._interrupt("websocket_error", str(exc))

            boundary_ready_items: int | None = None
            while True:
                if self._failure is not None:
                    raise self._failure

                overdue_lanes = tracker.overdue_silence_lanes(self._now_fn())
                if overdue_lanes:
                    # A timeout and a callback-bridge drain can become ready in
                    # the same event-loop turn.  Observe the queue work that
                    # was already admitted at the boundary, but take one
                    # bounded snapshot so continuous unrelated traffic cannot
                    # postpone a genuinely silent lane forever.
                    if boundary_ready_items is None:
                        await asyncio.sleep(0)
                        if self._failure is not None:
                            raise self._failure
                        boundary_ready_items = queue.qsize()
                    if boundary_ready_items > 0:
                        item = queue.get_nowait()
                        boundary_ready_items -= 1
                    else:
                        watchdog_now = self._now_fn()
                        still_overdue = tracker.overdue_silence_lanes(watchdog_now)
                        if still_overdue:
                            lane_text = ", ".join(
                                f"{lane.venue}/{lane.instrument_id}/{lane.timeframe}"
                                for lane in still_overdue
                            )
                            self._interrupt_and_raise(
                                "websocket_silence_detected",
                                f"causal silence deadline exceeded for lanes: {lane_text}",
                                interruption_time=watchdog_now,
                            )
                        boundary_ready_items = None
                        continue
                else:
                    boundary_ready_items = None
                    _earliest_lane, earliest_deadline = (
                        tracker.earliest_silence_deadline()
                    )
                    timeout_seconds = (
                        earliest_deadline - self._now_fn()
                    ).total_seconds()
                    if timeout_seconds <= 0:
                        continue
                    try:
                        async with asyncio.timeout(timeout_seconds):
                            item = await queue.get()
                    except TimeoutError:
                        continue
                self._observability.set_queue_utilization(
                    queue.qsize(),
                    self._queue_maxsize,
                )
                if self._failure is not None:
                    raise self._failure
                if item is _WAKE_SENTINEL:
                    continue

                observation = item
                if not isinstance(observation, CandleObservation):
                    self._interrupt_and_raise(
                        "websocket_malformed_payload",
                        "internal queue contained an invalid item",
                    )

                decision = tracker.classify(observation)
                if decision.kind == "ignore":
                    continue
                if decision.kind == "interrupt":
                    self._interrupt_and_raise(
                        decision.reason or "websocket_malformed_payload",
                        decision.detail,
                    )

                yield observation
                tracker.record_consumed(observation)
        finally:
            await self._cleanup()

    def _open_session(self) -> BinanceWebSocketSession:
        stream_names = sorted(
            f"{provider_symbol.lower()}@kline_{self._base_timeframe}"
            for _normalized_symbol, (_lane, provider_symbol) in self._routes.items()
        )
        try:
            return self._session_owner.open(
                loop=self._loop,
                stream_names=stream_names,
                on_open=self._on_open,
                on_message=self._on_message,
                on_close=self._on_close,
                on_error=self._on_error,
            )
        except RuntimeError as exc:
            raise LiveStreamInterrupted(
                reason="connection_lifecycle_busy",
                recovery_requests=(),
            ) from exc

    async def _cleanup(self) -> None:
        self._stream_finished = True
        self._intentional_stop = True
        self._callback_bridge.close()
        self._observability.set_websocket_connected(False)
        self._observability.set_queue_utilization(
            self._queue.qsize(),
            self._queue_maxsize,
        )
        session = self._session
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

    def _recovery_requests(
        self,
        reason: str,
        *,
        interruption_time: datetime | None = None,
    ) -> tuple[RecoveryRequest, ...]:
        return self._tracker.recovery_requests(
            reason,
            interruption_time=(
                self._now_fn() if interruption_time is None else interruption_time
            ),
        )

    def _wake_consumer(self) -> None:
        try:
            self._queue.put_nowait(_WAKE_SENTINEL)
            self._observability.set_queue_utilization(
                self._queue.qsize(),
                self._queue_maxsize,
            )
        except asyncio.QueueFull:
            pass

    def _interrupt(
        self,
        reason: str,
        detail: str | None = None,
        *,
        interruption_time: datetime | None = None,
    ) -> None:
        if self._intentional_stop or self._stream_finished or self._failure is not None:
            return
        self._failure = LiveStreamInterrupted(
            reason=reason,
            recovery_requests=self._recovery_requests(
                reason,
                interruption_time=interruption_time,
            ),
        )
        self._observability.record_websocket_interruption()
        self._observability.set_websocket_connected(False)
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
        self._wake_consumer()

    def _interrupt_and_raise(
        self,
        reason: str,
        detail: str | None = None,
        *,
        interruption_time: datetime | None = None,
    ) -> NoReturn:
        self._interrupt(reason, detail, interruption_time=interruption_time)
        if self._failure is None:
            raise RuntimeError(f"websocket interruption was not recorded: {reason}")
        raise self._failure

    def _request_bridge_drain(self) -> None:
        try:
            self._loop.call_soon_threadsafe(self._drain_callback_bridge)
        except RuntimeError:
            self._callback_bridge.cancel_scheduled_drain()

    def _offer_bridge_event(
        self,
        event: object,
        *,
        overflow_control: _BridgeControl,
    ) -> None:
        if self._callback_bridge.offer(event, overflow_control=overflow_control):
            self._request_bridge_drain()

    def _drain_callback_bridge(self) -> None:
        events, urgent_control = self._callback_bridge.take_batch()
        for event in events:
            if self._failure is not None or self._stream_finished:
                return
            if isinstance(event, _BridgeControl):
                self._interrupt(event.reason, event.detail)
                return
            if not isinstance(event, CandleObservation):
                self._interrupt(
                    "websocket_malformed_payload",
                    "callback bridge contained an invalid item",
                )
                return
            try:
                self._queue.put_nowait(event)
                self._observability.set_queue_utilization(
                    self._queue.qsize(),
                    self._queue_maxsize,
                )
            except asyncio.QueueFull:
                self._interrupt(
                    "websocket_queue_overflow",
                    "finalized candle queue is full",
                )
                return
        if (
            urgent_control is not None
            and self._failure is None
            and not self._stream_finished
        ):
            self._interrupt(urgent_control.reason, urgent_control.detail)

    def _on_open(self, _websocket: object, *_args: object) -> None:
        return None

    def _on_message(self, _websocket: object, raw_message: object) -> None:
        try:
            observation = self._parse_message(
                raw_message,
                routes=self._routes,
                base_timeframe=self._base_timeframe,
                timeframe_duration=self._timeframe_duration,
                alignment_origin=self._alignment_origin,
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
            self._offer_bridge_event(control, overflow_control=control)
            return
        if observation is None:
            return
        self._offer_bridge_event(
            observation,
            overflow_control=_BridgeControl(
                "websocket_queue_overflow",
                "finalized candle admission bridge is full",
            ),
        )

    def _on_close(self, _websocket: object, *_args: object) -> None:
        control = _BridgeControl("websocket_disconnected")
        self._offer_bridge_event(control, overflow_control=control)

    def _on_error(self, _websocket: object, error: object, *_args: object) -> None:
        control = _BridgeControl("websocket_error", str(error))
        self._offer_bridge_event(control, overflow_control=control)


__all__ = ["_ClosedCandlePump"]
