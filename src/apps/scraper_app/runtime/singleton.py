"""PostgreSQL advisory lock: at most one collector writes at a time."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)

# "SCRPV2_1" as a bigint; fixed so every process contends on the same lock.
ADVISORY_LOCK_KEY = 0x5343525056325F31


class LockConnection(Protocol):
    async def fetchval(self, query: str, *args: object) -> object: ...

    async def close(self) -> None: ...

    def is_closed(self) -> bool: ...


ConnectionFactory = Callable[[], Awaitable[LockConnection]]
Sleep = Callable[[float], Awaitable[None]]


class AdvisoryLock:
    """Session-level ``pg_try_advisory_lock`` on a dedicated connection.

    ``held`` is the only thing writers may trust: it turns false the moment the
    lock connection is found dead, because PostgreSQL then releases the lock and
    another instance may take it.
    """

    def __init__(
        self,
        connect: ConnectionFactory,
        *,
        key: int = ADVISORY_LOCK_KEY,
        check_interval_seconds: float = 5.0,
        backoff_seconds: tuple[float, ...] = (1.0, 2.0, 5.0, 15.0, 30.0),
        sleep: Sleep = asyncio.sleep,
        probe_timeout_seconds: float = 15.0,
    ) -> None:
        self._connect = connect
        self._key = key
        self._check_interval = check_interval_seconds
        self._backoff = backoff_seconds
        self._sleep = sleep
        self._probe_timeout = probe_timeout_seconds
        self._connection: LockConnection | None = None
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    async def try_acquire(self) -> bool:
        """Take the lock once; ``False`` when another session holds it."""
        if self._held:
            return True
        connection: LockConnection | None = None
        try:
            connection = await asyncio.wait_for(
                self._connect(), timeout=self._probe_timeout
            )
            acquired = await asyncio.wait_for(
                connection.fetchval("SELECT pg_try_advisory_lock($1)", self._key),
                timeout=self._probe_timeout,
            )
        except Exception:
            logger.warning(
                "advisory lock acquisition failed; lock is not held", exc_info=True
            )
            await self._discard(connection)
            return False
        if acquired is not True:
            await self._discard(connection)
            return False
        self._connection = connection
        self._held = True
        return True

    async def check(self) -> bool:
        """Probe the lock connection; mark the lock lost if it is dead."""
        connection = self._connection
        if not self._held or connection is None:
            return False
        try:
            if connection.is_closed():
                raise ConnectionError("lock connection is closed")
            await asyncio.wait_for(
                connection.fetchval("SELECT 1"), timeout=self._probe_timeout
            )
        except Exception:
            logger.exception(
                "advisory lock lost: connection probe failed; writes are stopped"
            )
            self._held = False
            self._connection = None
            await self._discard(connection)
            return False
        return True

    async def supervise(self) -> None:
        """Watch the lock; when it is lost, re-acquire with backoff."""
        attempt = 0
        while True:
            if self._held:
                attempt = 0
                await self._sleep(self._check_interval)
                await self.check()
                continue
            if await self.try_acquire():
                logger.info("advisory lock re-acquired; writes may resume")
                continue
            delay = self._backoff[min(attempt, len(self._backoff) - 1)]
            attempt += 1
            await self._sleep(delay)

    async def release(self) -> None:
        connection, self._connection = self._connection, None
        self._held = False
        # Closing the session releases the lock; no explicit unlock is needed.
        await self._discard(connection)

    @staticmethod
    async def _discard(connection: LockConnection | None) -> None:
        if connection is None:
            return
        try:
            await connection.close()
        except Exception:
            logger.debug("closing the lock connection failed", exc_info=True)


__all__ = ["ADVISORY_LOCK_KEY", "AdvisoryLock", "ConnectionFactory", "LockConnection"]
