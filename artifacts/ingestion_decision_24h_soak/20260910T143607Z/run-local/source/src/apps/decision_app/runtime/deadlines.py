"""Small monotonic deadline helpers for Decision-owned I/O boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from math import isfinite
from time import monotonic
from typing import Any


class OperationTimeout(TimeoutError):
    """Raised when one bounded Decision operation exhausts its budget."""

    def __init__(
        self, operation: str, timeout: float, *, source: str = "deadline"
    ) -> None:
        self.operation = operation
        self.timeout = timeout
        self.source = source
        if source == "deadline":
            message = f"{operation} exceeded its {timeout:g}s deadline"
        else:
            message = f"{operation} raised a native {source} timeout"
        super().__init__(message)


class CleanupTimeout(TimeoutError):
    """Raised when an owned resource cannot be released in its cleanup budget."""


@dataclass(frozen=True, slots=True)
class Deadline:
    """Absolute monotonic deadline shared by one composed operation."""

    expires_at: float

    @classmethod
    def after(cls, timeout: float) -> Deadline:
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not isfinite(float(timeout))
            or timeout <= 0
        ):
            raise ValueError("timeout must be finite and positive")
        return cls(monotonic() + float(timeout))

    def remaining(self) -> float:
        return max(0.0, self.expires_at - monotonic())


@dataclass(slots=True)
class CleanupBudget:
    """Lazily started cleanup allowance shared by one owning operation."""

    timeout: float
    cap_expires_at: float | None = None
    _deadline: Deadline | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout, bool)
            or not isinstance(self.timeout, (int, float))
            or not isfinite(float(self.timeout))
            or self.timeout <= 0
        ):
            raise ValueError("cleanup timeout must be finite and positive")
        self.timeout = float(self.timeout)
        if self.cap_expires_at is not None and not isfinite(self.cap_expires_at):
            raise ValueError("cleanup cap must be finite")

    def remaining(self) -> float:
        if self._deadline is None:
            expires_at = monotonic() + self.timeout
            if self.cap_expires_at is not None:
                expires_at = min(expires_at, self.cap_expires_at)
            self._deadline = Deadline(expires_at)
        return self._deadline.remaining()

    def deadline(self) -> Deadline:
        self.remaining()
        assert self._deadline is not None
        return self._deadline


def require_remaining(deadline: Deadline, *, operation: str) -> float:
    """Reject a new phase once an absolute operation deadline is exhausted."""

    remaining = deadline.remaining()
    if remaining <= 0:
        raise OperationTimeout(operation, 0.0)
    return remaining


def native_timeout_kwargs(
    deadline: Deadline | None,
    *,
    operation: str,
) -> dict[str, float]:
    """Return the explicit native timeout keyword for a driver command."""

    if deadline is None:
        return {}
    return {"timeout": require_remaining(deadline, operation=operation)}


async def run_with_timeout[T](
    awaitable: Awaitable[T],
    timeout: float | None,
    *,
    operation: str,
) -> T:
    """Await one operation without converting caller cancellation."""

    if timeout is None:
        return await awaitable
    timeout_value = float(timeout)
    if not isfinite(timeout_value) or timeout_value <= 0:
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        raise OperationTimeout(operation, 0.0)
    scope = asyncio.timeout(timeout_value)
    try:
        async with scope:
            result = await awaitable
        if scope.expired():
            raise OperationTimeout(operation, timeout_value)
        return result
    except OperationTimeout:
        raise
    except TimeoutError as exc:
        source = "deadline" if scope.expired() else "driver"
        raise OperationTimeout(operation, timeout_value, source=source) from exc


async def run_until[T](
    awaitable: Awaitable[T],
    deadline: Deadline,
    *,
    operation: str,
) -> T:
    """Await one phase using the remaining time of an absolute deadline."""

    return await run_with_timeout(awaitable, deadline.remaining(), operation=operation)


def _retain_cleanup_task(
    task: asyncio.Task[object],
    retained_tasks: set[asyncio.Task[object]],
) -> None:
    retained_tasks.add(task)

    def consume(completed: asyncio.Task[object]) -> None:
        retained_tasks.discard(completed)
        try:
            completed.exception()
        except BaseException:  # noqa: BLE001, S110
            pass

    task.add_done_callback(consume)


@asynccontextmanager
async def acquire_db_connection(
    pool: Any,
    *,
    deadline: Deadline | None,
    io_timeout_seconds: float | None,
    cleanup_timeout_seconds: float,
    retained_tasks: set[asyncio.Task[object]],
    cleanup_budget: CleanupBudget | None = None,
    poison: Callable[[], None] | None = None,
    operation: str,
):
    """Own one asyncpg lease without closing a borrowed pool."""

    if deadline is None:
        async with pool.acquire() as connection:
            yield connection
        return
    if cleanup_budget is None:
        cleanup_budget = CleanupBudget(cleanup_timeout_seconds)

    remaining = require_remaining(deadline, operation=f"{operation} acquisition")
    acquire_timeout = remaining
    if io_timeout_seconds is not None:
        acquire_timeout = min(acquire_timeout, float(io_timeout_seconds))
    acquire_context = pool.acquire(timeout=acquire_timeout)
    connection = await run_with_timeout(
        acquire_context.__aenter__(),
        acquire_timeout,
        operation=f"{operation} acquisition",
    )
    body_error: BaseException | None = None
    try:
        try:
            yield connection
        except BaseException as exc:
            body_error = exc
            raise
    finally:
        current = asyncio.current_task()
        externally_cancelled = current is not None and current.cancelling() > 0
        remaining = deadline.remaining()
        release_timeout = (
            cleanup_budget.remaining()
            if (
                externally_cancelled
                or remaining <= 0
                or isinstance(body_error, (OperationTimeout, CleanupTimeout))
            )
            else remaining
        )
        try:
            await cleanup_with_timeout(
                pool.release(connection, timeout=release_timeout),
                release_timeout,
                operation=f"{operation} lease release",
                retained_tasks=retained_tasks,
            )
        except BaseException as cleanup_error:
            if poison is not None:
                poison()
            # asyncpg's supported discard path is terminate(); never close a
            # pool that may be borrowed by another application.
            terminate = getattr(connection, "terminate", None)
            if callable(terminate):
                try:
                    terminate()
                except Exception:  # noqa: BLE001, S110
                    pass
            if isinstance(cleanup_error, asyncio.CancelledError):
                raise
            if body_error is not None:
                raise body_error
            raise


async def cleanup_with_timeout(
    awaitable: Awaitable[object],
    timeout: float,
    *,
    operation: str,
    retained_tasks: set[asyncio.Task[object]],
) -> None:
    """Bound cleanup while retaining ownership of cancellation-resistant work."""

    task = asyncio.ensure_future(awaitable)
    current = asyncio.current_task()
    initial_cancelling = current.cancelling() if current is not None else 0
    try:
        timeout_value = float(timeout)
        if not isfinite(timeout_value) or timeout_value <= 0:
            raise TimeoutError
        await asyncio.wait_for(asyncio.shield(task), timeout_value)
        current = asyncio.current_task()
        new_cancellation = (
            current is not None and current.cancelling() > initial_cancelling
        )
        if new_cancellation:
            if not task.done():
                task.cancel()
            _retain_cleanup_task(task, retained_tasks)
            raise asyncio.CancelledError
    except asyncio.CancelledError:
        current = asyncio.current_task()
        child_cancelled = task.done() and task.cancelled()
        caller_cancelled = (
            current is not None and current.cancelling() > initial_cancelling
        )
        if child_cancelled and not caller_cancelled:
            _retain_cleanup_task(task, retained_tasks)
            raise CleanupTimeout(
                f"{operation} cleanup task was cancelled before release was confirmed"
            )
        if not task.done():
            task.cancel()
        _retain_cleanup_task(task, retained_tasks)
        raise
    except TimeoutError as exc:
        if not task.done():
            task.cancel()
        _retain_cleanup_task(task, retained_tasks)
        raise CleanupTimeout(
            f"{operation} exceeded its {timeout:g}s cleanup deadline"
        ) from exc


__all__ = [
    "CleanupBudget",
    "CleanupTimeout",
    "Deadline",
    "OperationTimeout",
    "acquire_db_connection",
    "cleanup_with_timeout",
    "native_timeout_kwargs",
    "require_remaining",
    "run_until",
    "run_with_timeout",
]
