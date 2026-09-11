"""Owned transport operations with explicit completion and abandonment handshakes."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from threading import Event, Lock, Thread
from typing import Any

_LOGGER = logging.getLogger(__name__)


class _OwnedCallTimeout(TimeoutError):
    """The caller's wait expired; the owned operation may still be running."""

    def __init__(self, *, deadline: float) -> None:
        self.deadline = deadline
        super().__init__("owned operation wait expired")


class _OwnedBlockingCall:
    """Run one blocking SDK operation without losing ownership on timeout."""

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        operation: Callable[[], Any],
        name: str,
        abandoned_cleanup: Callable[[Any], None] | None = None,
        finished_callback: Callable[[_OwnedBlockingCall], None] | None = None,
    ) -> None:
        self._loop = loop
        self._operation = operation
        self._abandoned_cleanup = abandoned_cleanup
        self._finished_callback = finished_callback
        # The future is only a completion signal.  Results and failures stay on
        # the owned call so a shield timeout cannot leave a Future holding an
        # SDK payload or an unconsumed exception.
        self._future = loop.create_future()
        self._decision = Event()
        self._lock = Lock()
        self._operation_finished = False
        self._operation_finished_at: float | None = None
        self._adopted = False
        self._abandoned = False
        self._finished = False
        self._operation_result: Any = None
        self._operation_error: BaseException | None = None
        self._cleanup_error: BaseException | None = None
        self._thread = Thread(target=self._run, name=name, daemon=True)

    @property
    def future(self) -> asyncio.Future[None]:
        return self._future

    @property
    def adopted(self) -> bool:
        with self._lock:
            return self._adopted

    @property
    def operation_finished(self) -> bool:
        with self._lock:
            return self._operation_finished

    @property
    def operation_finished_at(self) -> float | None:
        with self._lock:
            return self._operation_finished_at

    @property
    def finished(self) -> bool:
        with self._lock:
            return self._finished

    @property
    def failed(self) -> bool:
        with self._lock:
            return self._operation_error is not None or self._cleanup_error is not None

    @property
    def cleanup_failed(self) -> bool:
        with self._lock:
            return self._cleanup_error is not None

    async def wait(self, timeout: float | None = None) -> Any:
        if timeout is None:
            await asyncio.shield(self._future)
        else:
            deadline = time.monotonic() + timeout
            try:
                await asyncio.wait_for(asyncio.shield(self._future), timeout=timeout)
            except TimeoutError as exc:
                raise _OwnedCallTimeout(deadline=deadline) from exc
        return self.result_or_raise()

    def result_or_raise(self) -> Any:
        with self._lock:
            error = self._operation_error
            result = self._operation_result
        if error is not None:
            raise error
        return result

    def start(self) -> None:
        try:
            self._thread.start()
        except BaseException:
            with self._lock:
                self._operation_finished = True
                self._operation_finished_at = time.monotonic()
                self._abandoned = True
                self._finished = True
                self._decision.set()
            self._publish_completion()
            if self._abandoned_cleanup is not None:
                try:
                    self._abandoned_cleanup(None)
                except BaseException as exc:  # noqa: BLE001 - cleanup is best effort
                    with self._lock:
                        self._cleanup_error = exc
                    _LOGGER.warning("owned SDK start-failure cleanup failed: %s", exc)
            if self._finished_callback is not None:
                try:
                    self._finished_callback(self)
                except BaseException as exc:  # noqa: BLE001
                    _LOGGER.warning("owned SDK start-failure release failed: %s", exc)
            raise

    def adopt(self) -> bool:
        """Claim the operation result, or report that abandonment won."""
        with self._lock:
            if self._adopted:
                return True
            if self._abandoned or not self._operation_finished:
                return False
            self._adopted = True
            self._decision.set()
            return True

    def abandon(self) -> None:
        """Release ownership; the worker performs cleanup after the call."""
        with self._lock:
            if self._adopted or self._abandoned:
                return
            self._abandoned = True
            finished = self._finished
            self._decision.set()
            if finished:
                self._operation_result = None
                self._operation_error = None

    def _publish_completion(self) -> None:
        def resolve() -> None:
            if not self._future.done():
                self._future.set_result(None)

        try:
            self._loop.call_soon_threadsafe(resolve)
        except RuntimeError:
            # The worker still owns cleanup if the event loop is already closed.
            return

    def _run(self) -> None:
        result: Any = None
        try:
            result = self._operation()
        except BaseException as exc:  # noqa: BLE001 - preserve SDK failures
            with self._lock:
                self._operation_finished = True
                self._operation_finished_at = time.monotonic()
                self._operation_error = exc
            self._publish_completion()
        else:
            with self._lock:
                self._operation_finished = True
                self._operation_finished_at = time.monotonic()
                self._operation_result = result
            self._publish_completion()

        with self._lock:
            abandoned = self._abandoned
            adopted = self._adopted
        if not abandoned and not adopted:
            self._decision.wait()
            with self._lock:
                abandoned = self._abandoned

        if abandoned and self._abandoned_cleanup is not None:
            try:
                self._abandoned_cleanup(result)
            except BaseException as exc:  # noqa: BLE001 - cleanup is best effort
                with self._lock:
                    self._cleanup_error = exc
                _LOGGER.warning("owned SDK cleanup failed: %s", exc)

        with self._lock:
            self._finished = True
        if self._finished_callback is not None:
            try:
                self._finished_callback(self)
            except BaseException as exc:  # noqa: BLE001 - release is best effort
                _LOGGER.warning("owned SDK lifecycle release failed: %s", exc)
        if abandoned:
            with self._lock:
                self._operation_result = None
                self._operation_error = None


class _OwnedAsyncCall:
    """Own one async SDK operation until its task actually returns."""

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        operation: Callable[[], Awaitable[Any]],
        name: str,
        finished_callback: Callable[[_OwnedAsyncCall], None] | None = None,
    ) -> None:
        self._loop = loop
        self._operation = operation
        self._name = name
        self._finished_callback = finished_callback
        self._future = loop.create_future()
        self._lock = Lock()
        self._operation_finished = False
        self._operation_finished_at: float | None = None
        self._adopted = False
        self._abandoned = False
        self._finished = False
        self._operation_result: Any = None
        self._operation_error: BaseException | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def future(self) -> asyncio.Future[None]:
        return self._future

    @property
    def adopted(self) -> bool:
        with self._lock:
            return self._adopted

    @property
    def operation_finished(self) -> bool:
        with self._lock:
            return self._operation_finished

    @property
    def operation_finished_at(self) -> float | None:
        with self._lock:
            return self._operation_finished_at

    @property
    def finished(self) -> bool:
        with self._lock:
            return self._finished

    @property
    def failed(self) -> bool:
        with self._lock:
            return self._operation_error is not None

    async def wait(self, timeout: float | None = None) -> Any:
        if timeout is None:
            await asyncio.shield(self._future)
        else:
            deadline = time.monotonic() + timeout
            try:
                await asyncio.wait_for(asyncio.shield(self._future), timeout=timeout)
            except TimeoutError as exc:
                raise _OwnedCallTimeout(deadline=deadline) from exc
        return self.result_or_raise()

    def result_or_raise(self) -> Any:
        with self._lock:
            error = self._operation_error
            result = self._operation_result
        if error is not None:
            raise error
        return result

    def start(self) -> None:
        operation = self._run()
        try:
            self._task = self._loop.create_task(operation, name=self._name)
        except BaseException as exc:
            operation.close()
            with self._lock:
                self._operation_finished = True
                self._operation_finished_at = time.monotonic()
                self._operation_error = exc
                self._abandoned = True
                self._finished = True
            if not self._future.done():
                self._future.set_result(None)
            if self._finished_callback is not None:
                try:
                    self._finished_callback(self)
                except BaseException as release_exc:  # noqa: BLE001
                    _LOGGER.warning(
                        "owned async SDK start-failure release failed: %s",
                        release_exc,
                    )
            raise

    def adopt(self) -> bool:
        with self._lock:
            if self._adopted:
                return True
            if self._abandoned or not self._operation_finished:
                return False
            self._adopted = True
            return True

    def abandon(self) -> None:
        with self._lock:
            if self._adopted or self._abandoned:
                return
            self._abandoned = True
            if self._finished:
                self._operation_result = None
                self._operation_error = None

    async def _run(self) -> None:
        try:
            result = await self._operation()
        except BaseException as exc:  # noqa: BLE001 - preserve SDK failures
            with self._lock:
                self._operation_finished = True
                self._operation_finished_at = time.monotonic()
                self._operation_error = exc
        else:
            with self._lock:
                self._operation_finished = True
                self._operation_finished_at = time.monotonic()
                self._operation_result = result

        if not self._future.done():
            self._future.set_result(None)
        with self._lock:
            self._finished = True
            abandoned = self._abandoned
        if self._finished_callback is not None:
            try:
                self._finished_callback(self)
            except BaseException as exc:  # noqa: BLE001 - release is best effort
                _LOGGER.warning("owned async SDK release failed: %s", exc)
        if abandoned:
            with self._lock:
                self._operation_result = None
                self._operation_error = None


__all__ = ["_OwnedAsyncCall", "_OwnedBlockingCall", "_OwnedCallTimeout"]
