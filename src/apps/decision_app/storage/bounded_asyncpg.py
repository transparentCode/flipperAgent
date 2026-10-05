"""Shared bounded-asyncpg plumbing for the decision storage repositories."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from apps.decision_app.runtime.deadlines import (
    CleanupBudget,
    Deadline,
    cleanup_with_timeout,
    require_remaining,
    run_until,
)


class BoundedAsyncpgRepository:
    """Deadline, cleanup-budget and poisoning state shared by asyncpg repositories."""

    _POISONED_MESSAGE: str

    def __init__(
        self,
        pool: Any,
        *,
        io_timeout_seconds: float | None = None,
        operation_timeout_seconds: float | None = None,
        cleanup_timeout_seconds: float | None = None,
        validate_after_pool: Callable[[], None] | None = None,
    ) -> None:
        if pool is None or not hasattr(pool, "acquire"):
            raise TypeError("pool must provide asyncpg acquire()")
        if validate_after_pool is not None:
            validate_after_pool()
        for value in (
            io_timeout_seconds,
            operation_timeout_seconds,
            cleanup_timeout_seconds,
        ):
            if value is not None:
                Deadline.after(value)
        if operation_timeout_seconds is not None and cleanup_timeout_seconds is None:
            cleanup_timeout_seconds = 5.0
        self._pool = pool
        self._io_timeout_seconds = io_timeout_seconds
        self._operation_timeout_seconds = operation_timeout_seconds
        self._cleanup_timeout_seconds = cleanup_timeout_seconds
        self._retained_cleanup_tasks: set[Any] = set()
        self._poisoned = False

    def _begin(self) -> Deadline | None:
        self._ensure_usable()
        if self._operation_timeout_seconds is None:
            return None
        return Deadline.after(self._operation_timeout_seconds)

    async def _phase(
        self,
        awaitable: Any,
        deadline: Deadline | None,
        operation: str,
    ) -> Any:
        if deadline is None:
            return await awaitable
        return await run_until(awaitable, deadline, operation=operation)

    def _finish(self, deadline: Deadline | None, operation: str) -> None:
        if deadline is not None:
            require_remaining(deadline, operation=operation)

    def _poison(self) -> None:
        self._poisoned = True

    @property
    def poisoned(self) -> bool:
        return self._poisoned

    def _ensure_usable(self) -> None:
        if self._poisoned:
            raise RuntimeError(self._POISONED_MESSAGE)

    async def _run_in_transaction[Result](
        self,
        connection: Any,
        *,
        deadline: Deadline | None,
        cleanup_budget: CleanupBudget,
        label: str,
        locked: Callable[[Deadline | None], Awaitable[Result]],
    ) -> Result:
        transaction = getattr(connection, "transaction", None)
        if callable(transaction) and deadline is None:
            async with connection.transaction():
                return await locked(None)
        if callable(transaction):
            tx = connection.transaction()
            if deadline is not None:
                require_remaining(
                    deadline,
                    operation=f"{label} transaction begin",
                )
            await self._phase(tx.start(), deadline, f"{label} transaction begin")
            try:
                result = await locked(deadline)
            except BaseException:
                try:
                    await cleanup_with_timeout(
                        tx.rollback(),
                        cleanup_budget.remaining(),
                        operation=f"{label} transaction rollback",
                        retained_tasks=self._retained_cleanup_tasks,
                    )
                except BaseException:  # noqa: BLE001
                    self._poison()
                raise
            if deadline is not None:
                require_remaining(
                    deadline,
                    operation=f"{label} transaction commit",
                )
            await self._phase(
                tx.commit(),
                deadline,
                f"{label} transaction commit",
            )
            return result
        return await locked(deadline)


__all__ = ["BoundedAsyncpgRepository"]
