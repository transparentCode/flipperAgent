"""Binance websocket SDK session lifecycle ownership."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from threading import Lock
from typing import Any

from apps.ingestion_app.providers.base import (
    TransportDeadlineExceeded,
)
from apps.ingestion_app.transport.ownership import (
    OwnedBlockingCall,
    OwnedCallTimeout,
)
from libs.common.exceptions import DataIngestionError


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


class BinanceWebSocketSessionOwner:
    """Own manager-level lifecycle state and create one active SDK session."""

    def __init__(
        self,
        *,
        stream_url: str,
        lifecycle_timeout_seconds: float,
        client_factory: Callable[..., Any],
        provider_id: str,
    ) -> None:
        self.stream_url = stream_url
        self.lifecycle_timeout_seconds = lifecycle_timeout_seconds
        self.client_factory = client_factory
        self.provider_id = provider_id
        self._lifecycle_lock = Lock()
        self._lifecycle_active = False
        self._lifecycle_quarantined = False
        self._lifecycle_quarantine_error: DataIngestionError | None = None
        self._owned_calls: set[OwnedBlockingCall] = set()

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

    def open(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        stream_names: list[str],
        on_open: Callable[..., object],
        on_message: Callable[..., object],
        on_close: Callable[..., object],
        on_error: Callable[..., object],
    ) -> BinanceWebSocketSession:
        lease = self._acquire_lifecycle()
        return BinanceWebSocketSession(
            owner=self,
            loop=loop,
            lease=lease,
            stream_names=stream_names,
            on_open=on_open,
            on_message=on_message,
            on_close=on_close,
            on_error=on_error,
        )

    def _track_call(self, call: OwnedBlockingCall) -> None:
        with self._lifecycle_lock:
            self._owned_calls.add(call)

    def _forget_call(self, call: OwnedBlockingCall) -> None:
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

    def _start_blocking_call(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        operation: Callable[[], Any],
        name: str,
        abandoned_cleanup: Callable[[Any], None] | None,
        finished_callback: Callable[[OwnedBlockingCall], None],
    ) -> OwnedBlockingCall:
        call = OwnedBlockingCall(
            loop=loop,
            operation=operation,
            name=name,
            abandoned_cleanup=abandoned_cleanup,
            finished_callback=finished_callback,
        )
        self._track_call(call)
        call.start()
        return call

    async def _wait_for_lifecycle_call(
        self,
        call: OwnedBlockingCall,
        *,
        operation: str,
        abandon_on_error: bool = True,
    ) -> Any:
        try:
            result = await call.wait(self.lifecycle_timeout_seconds)
        except OwnedCallTimeout as exc:
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


class BinanceWebSocketSession:
    """Own construction, subscription, stop, and cleanup for one client."""

    def __init__(
        self,
        *,
        owner: BinanceWebSocketSessionOwner,
        loop: asyncio.AbstractEventLoop,
        lease: _LifecycleLease,
        stream_names: list[str],
        on_open: Callable[..., object],
        on_message: Callable[..., object],
        on_close: Callable[..., object],
        on_error: Callable[..., object],
    ) -> None:
        self._owner = owner
        self._loop = loop
        self._lease = lease
        self._stream_names = stream_names
        self._callbacks = {
            "on_open": on_open,
            "on_message": on_message,
            "on_close": on_close,
            "on_error": on_error,
        }
        self._client: Any | None = None
        self._factory_call: OwnedBlockingCall | None = None
        self._subscription_call: OwnedBlockingCall | None = None
        self._stop_call: OwnedBlockingCall | None = None
        self._stop_controller = _ExactlyOnceStop()

    @property
    def client(self) -> Any | None:
        return self._client

    async def start(self) -> None:
        self._factory_call = self._owner._start_blocking_call(
            loop=self._loop,
            operation=lambda: self._owner.client_factory(
                stream_url=self._owner.stream_url,
                on_open=self._callbacks["on_open"],
                on_message=self._callbacks["on_message"],
                on_close=self._callbacks["on_close"],
                on_error=self._callbacks["on_error"],
                is_combined=True,
            ),
            name="binance-websocket-factory",
            abandoned_cleanup=self._stop_client_with_bounded_reap,
            finished_callback=self._finish_abandoned_call,
        )
        self._client = await self._owner._wait_for_lifecycle_call(
            self._factory_call,
            operation="websocket factory",
        )
        self._stop_controller.bind(self._client)
        self._subscription_call = self._owner._start_blocking_call(
            loop=self._loop,
            operation=lambda: self._client.subscribe(self._stream_names),
            name="binance-websocket-subscribe",
            abandoned_cleanup=lambda _result: self._stop_client_with_bounded_reap(
                self._client
            ),
            finished_callback=self._finish_abandoned_call,
        )
        await self._owner._wait_for_lifecycle_call(
            self._subscription_call,
            operation="websocket subscribe",
        )

    def abandon_pending_calls(self) -> None:
        for call in (self._subscription_call, self._factory_call):
            if call is not None and not call.adopted:
                call.abandon()

    async def close(self) -> None:
        self.abandon_pending_calls()
        construction_still_owns_client = any(
            call is not None and not call.adopted and not call.finished
            for call in (self._factory_call, self._subscription_call)
        )
        if self._client is not None and not construction_still_owns_client:
            await self._stop_client_once(self._client)
        elif self._client is None and self._factory_call is None:
            self._lease.release()

    def _finish_abandoned_call(self, call: OwnedBlockingCall) -> None:
        if not call.adopted:
            if call.cleanup_failed:
                self._owner._quarantine_lifecycle(
                    DataIngestionError(
                        "Binance websocket lifecycle cleanup failed; "
                        "lifecycle quarantined"
                    )
                )
            self._lease.release()
        self._owner._forget_call(call)

    def _finish_stop(self, call: OwnedBlockingCall) -> None:
        if call.failed:
            self._owner._quarantine_lifecycle(
                DataIngestionError(
                    "Binance websocket lifecycle cleanup failed; lifecycle quarantined"
                )
            )
        self._lease.release()
        self._owner._forget_call(call)

    def _stop_client_with_bounded_reap(self, client_to_stop: Any | None) -> None:
        if client_to_stop is None:
            return
        self._stop_controller.bind(client_to_stop)
        try:
            self._stop_controller.run(client_to_stop)
        except BrokenPipeError:
            socket_manager = getattr(client_to_stop, "socket_manager", None)
            join = getattr(socket_manager, "join", None)
            is_alive = getattr(socket_manager, "is_alive", None)
            if not callable(join) or not callable(is_alive):
                raise
            join(self._owner.lifecycle_timeout_seconds)
            if is_alive():
                raise RuntimeError(
                    "Binance websocket socket-manager thread did not terminate"
                )

    async def _stop_client_once(self, client_to_stop: Any) -> None:
        if self._stop_call is None:
            self._stop_call = self._owner._start_blocking_call(
                loop=self._loop,
                operation=lambda: self._stop_client_with_bounded_reap(client_to_stop),
                name="binance-websocket-stop",
                abandoned_cleanup=None,
                finished_callback=self._finish_stop,
            )
        await self._owner._wait_for_lifecycle_call(
            self._stop_call,
            operation="websocket stop",
            abandon_on_error=False,
        )


__all__ = [
    "BinanceWebSocketSession",
    "BinanceWebSocketSessionOwner",
]
