import asyncio
import os
from typing import ClassVar, Optional

import asyncpg

from libs.common.config import ConfigManager
from libs.common.logging.logger_utils import bind_logger
from libs.common.enums import SystemComponent

logger = bind_logger(__name__, system_component=SystemComponent.CORE_INFRASTRUCTURE)

class DBPoolManager:
    _writer_pool: Optional[asyncpg.Pool] = None
    _reader_pool: Optional[asyncpg.Pool] = None
    _init_lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    @classmethod
    async def init_pools(cls, config_manager: Optional[ConfigManager] = None) -> None:
        """
        Initialize the reader and writer connection pools using asyncpg.
        """
        async with cls._init_lock:
            if cls._writer_pool is not None:
                return  # already initialized

            if config_manager is None:
                config_manager = ConfigManager()

            dsn = os.getenv("POSTGRES_URI")
            min_size = config_manager.get("postgres.pool.min_size", 2)
            max_size = config_manager.get("postgres.pool.max_size", 10)

            if dsn:
                pool_kwargs: dict = dict(dsn=dsn, min_size=min_size, max_size=max_size)
                _log_target = dsn.split("@")[-1] if "@" in dsn else "(env)"
            else:
                user = config_manager.get("postgres.user", "postgres")
                password = config_manager.get("postgres.password", "postgres")
                host = config_manager.get("postgres.host", "localhost")
                port = config_manager.get("postgres.port", 5432)
                database = config_manager.get("postgres.database", "flipper")
                pool_kwargs = dict(
                    user=user, password=password, host=host, port=int(port),
                    database=database, min_size=min_size, max_size=max_size,
                )
                _log_target = f"{host}:{port}/{database}"

            logger.info(f"Initializing writer DB pool \u2192 {_log_target}")
            for _ in range(30):
                try:
                    cls._writer_pool = await asyncpg.create_pool(**pool_kwargs)
                    break
                except Exception as e:
                    logger.warning(f"Waiting for writer DB pool... {type(e).__name__}")
                    await asyncio.sleep(1)
            if cls._writer_pool is None:
                raise RuntimeError("Failed to connect to writer database after 30 retries")

            logger.info(f"Initializing reader DB pool \u2192 {_log_target}")
            # In v1, reader points to the same DSN
            for _ in range(30):
                try:
                    cls._reader_pool = await asyncpg.create_pool(**pool_kwargs)
                    break
                except Exception as e:
                    logger.warning(f"Waiting for reader DB pool... {type(e).__name__}")
                    await asyncio.sleep(1)
            if cls._reader_pool is None:
                raise RuntimeError("Failed to connect to reader database after 30 retries")

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
            raise RuntimeError("Writer pool has not been initialized. Call init_pools() first.")
        return cls._writer_pool

    @classmethod
    def get_reader_pool(cls) -> asyncpg.Pool:
        if cls._reader_pool is None:
            raise RuntimeError("Reader pool has not been initialized. Call init_pools() first.")
        return cls._reader_pool
