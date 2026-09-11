import asyncio
import os
from collections.abc import Callable
from math import isfinite
from time import monotonic
from typing import ClassVar

import asyncpg

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.CORE_INFRASTRUCTURE)


class DBPoolManager:
    _writer_pool: asyncpg.Pool | None = None
    _reader_pool: asyncpg.Pool | None = None
    _init_lock: ClassVar[asyncio.Lock] = asyncio.Lock()
    _retained_cleanup_tasks: ClassVar[set[asyncio.Task[object]]] = set()

    @classmethod
    def _retain_cleanup_task(
        cls,
        task: asyncio.Task[object],
        owner_tasks: set[asyncio.Task[object]] | None = None,
    ) -> None:
        cls._retained_cleanup_tasks.add(task)
        if owner_tasks is not None:
            owner_tasks.add(task)

        def consume(completed: asyncio.Task[object]) -> None:
            cls._retained_cleanup_tasks.discard(completed)
            if owner_tasks is not None:
                owner_tasks.discard(completed)
            try:
                completed.exception()
            except BaseException:  # noqa: BLE001, S110
                pass

        task.add_done_callback(consume)

    @classmethod
    async def _close_pool_bounded(
        cls,
        pool: asyncpg.Pool,
        *,
        timeout: float | None,
        owner_tasks: set[asyncio.Task[object]] | None = None,
    ) -> None:
        if timeout is None:
            await pool.close()
            return
        task = asyncio.ensure_future(pool.close())
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout)
        except asyncio.CancelledError:
            if not task.done():
                task.cancel()
                cls._retain_cleanup_task(task, owner_tasks)
            terminate = getattr(pool, "terminate", None)
            if callable(terminate):
                terminate()
            raise
        except TimeoutError:
            if not task.done():
                task.cancel()
                cls._retain_cleanup_task(task, owner_tasks)
            terminate = getattr(pool, "terminate", None)
            if callable(terminate):
                terminate()

    @classmethod
    async def _reset_partial_state(
        cls,
        *,
        cleanup_timeout: float | None = None,
        owner_tasks: set[asyncio.Task[object]] | None = None,
        cleanup_remaining: Callable[[], float] | None = None,
    ) -> None:
        """Close any partially initialized pools before retrying init."""
        cleanup_deadline = (
            None if cleanup_timeout is None else monotonic() + float(cleanup_timeout)
        )

        def remaining() -> float | None:
            if cleanup_remaining is not None:
                return max(0.0, float(cleanup_remaining()))
            if cleanup_deadline is None:
                return None
            return max(0.0, cleanup_deadline - monotonic())

        if cls._writer_pool is not None:
            await cls._close_pool_bounded(
                cls._writer_pool,
                timeout=remaining(),
                owner_tasks=owner_tasks,
            )
            cls._writer_pool = None
        if cls._reader_pool is not None:
            await cls._close_pool_bounded(
                cls._reader_pool,
                timeout=remaining(),
                owner_tasks=owner_tasks,
            )
            cls._reader_pool = None

    @classmethod
    async def init_pools(
        cls,
        config_manager: ConfigManager | None = None,
        *,
        connect_timeout: float | None = None,
        return_created: bool = False,
        cleanup_timeout: float | None = None,
        retained_cleanup_tasks: set[asyncio.Task[object]] | None = None,
        cleanup_remaining: Callable[[], float] | None = None,
    ) -> bool | None:
        """
        Initialize the reader and writer connection pools using asyncpg.

        Returns whether this call created the shared pools.  A false result is
        an explicit borrowed-resource signal for application lifespans.
        """
        if connect_timeout is not None and (
            isinstance(connect_timeout, bool)
            or not isinstance(connect_timeout, (int, float))
            or not isfinite(float(connect_timeout))
            or connect_timeout <= 0
        ):
            raise ValueError("connect_timeout must be finite and positive")
        if cleanup_timeout is not None and (
            isinstance(cleanup_timeout, bool)
            or not isinstance(cleanup_timeout, (int, float))
            or not isfinite(float(cleanup_timeout))
            or cleanup_timeout <= 0
        ):
            raise ValueError("cleanup_timeout must be finite and positive")
        async with cls._init_lock:
            if return_created and cls._retained_cleanup_tasks:
                raise RuntimeError(
                    "Decision DB cleanup remains unconfirmed; pool reuse is fenced"
                )
            if cls._writer_pool is not None and cls._reader_pool is not None:
                return False if return_created else None  # already initialized

            if cls._writer_pool is not None or cls._reader_pool is not None:
                if return_created:
                    raise RuntimeError(
                        "partial DB pool state is pre-existing; Decision ownership "
                        "cannot be proven"
                    )
                logger.warning(
                    "Partial DB pool state detected; resetting pools before re-initialization"
                )
                await cls._reset_partial_state()

            if config_manager is None:
                config_manager = ConfigManager()

            dsn = os.getenv("POSTGRES_URI")
            min_size = config_manager.get("postgres.pool.min_size", 2)
            max_size = config_manager.get("postgres.pool.max_size", 10)

            if dsn:
                pool_kwargs: dict = {
                    "dsn": dsn,
                    "min_size": min_size,
                    "max_size": max_size,
                }
                _log_target = dsn.split("@")[-1] if "@" in dsn else "(env)"
            else:
                user = config_manager.get("postgres.user", "postgres")
                password = config_manager.get("postgres.password", "postgres")
                host = config_manager.get("postgres.host", "localhost")
                port = config_manager.get("postgres.port", 5432)
                database = config_manager.get("postgres.database", "flipper")
                pool_kwargs = {
                    "user": user,
                    "password": password,
                    "host": host,
                    "port": int(port),
                    "database": database,
                    "min_size": min_size,
                    "max_size": max_size,
                }
                _log_target = f"{host}:{port}/{database}"
            if connect_timeout is not None:
                pool_kwargs["timeout"] = float(connect_timeout)

            try:
                logger.info(f"Initializing writer DB pool \u2192 {_log_target}")
                for _ in range(30):
                    try:
                        cls._writer_pool = await asyncpg.create_pool(**pool_kwargs)
                        break
                    except Exception as e:  # noqa: BLE001
                        logger.warning(
                            f"Waiting for writer DB pool... {type(e).__name__}"
                        )
                        await asyncio.sleep(1)
                if cls._writer_pool is None:
                    raise RuntimeError(
                        "Failed to connect to writer database after 30 retries"
                    )

                logger.info(f"Initializing reader DB pool \u2192 {_log_target}")
                # In v1, reader points to the same DSN
                for _ in range(30):
                    try:
                        cls._reader_pool = await asyncpg.create_pool(**pool_kwargs)
                        break
                    except Exception as e:  # noqa: BLE001
                        logger.warning(
                            f"Waiting for reader DB pool... {type(e).__name__}"
                        )
                        await asyncio.sleep(1)
                if cls._reader_pool is None:
                    raise RuntimeError(
                        "Failed to connect to reader database after 30 retries"
                    )
            except BaseException as original_error:
                # Preserve the historical default cancellation behavior: a
                # caller cancelling reader initialization did not close a
                # writer pool that may have been created by this call.  The
                # Decision opt-in owns bounded partial cleanup explicitly.
                if (
                    isinstance(original_error, asyncio.CancelledError)
                    and not return_created
                ):
                    raise
                try:
                    await cls._reset_partial_state(
                        cleanup_timeout=cleanup_timeout if return_created else None,
                        owner_tasks=retained_cleanup_tasks if return_created else None,
                        cleanup_remaining=cleanup_remaining if return_created else None,
                    )
                except BaseException:  # noqa: BLE001
                    if isinstance(original_error, asyncio.CancelledError):
                        raise original_error

                raise
            return True if return_created else None

    @classmethod
    async def close_pools(cls) -> None:
        """
        Gracefully close reader and writer pools.
        """
        if cls._writer_pool is not None:
            logger.info("Closing writer DB pool")
            await cls._writer_pool.close()
            cls._writer_pool = None

        if cls._reader_pool is not None:
            logger.info("Closing reader DB pool")
            await cls._reader_pool.close()
            cls._reader_pool = None

    @classmethod
    def get_writer_pool(cls) -> asyncpg.Pool:
        if cls._writer_pool is None:
            raise RuntimeError(
                "Writer pool has not been initialized. Call init_pools() first."
            )
        return cls._writer_pool

    @classmethod
    def get_reader_pool(cls) -> asyncpg.Pool:
        if cls._reader_pool is None:
            raise RuntimeError(
                "Reader pool has not been initialized. Call init_pools() first."
            )
        return cls._reader_pool
