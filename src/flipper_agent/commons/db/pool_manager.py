import asyncpg
from typing import Optional
from flipper_agent.commons.config import ConfigManager
from flipper_agent.commons.logging.logger_utils import bind_logger
from flipper_agent.commons.enums import SystemComponent

logger = bind_logger(__name__, system_component=SystemComponent.CORE_INFRASTRUCTURE)

class DBPoolManager:
    _writer_pool: Optional[asyncpg.Pool] = None
    _reader_pool: Optional[asyncpg.Pool] = None

    @classmethod
    async def init_pools(cls, config_manager: Optional[ConfigManager] = None) -> None:
        """
        Initialize the reader and writer connection pools using asyncpg.
        """
        if config_manager is None:
            config_manager = ConfigManager()

        import os
        dsn = os.getenv("POSTGRES_URI")
        if not dsn:
            user = config_manager.get("postgres.user", "postgres")
            password = config_manager.get("postgres.password", "postgres")
            host = config_manager.get("postgres.host", "localhost")
            port = config_manager.get("postgres.port", 5432)
            database = config_manager.get("postgres.database", "flipper")
            dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"

        min_size = config_manager.get("postgres.pool.min_size", 2)
        max_size = config_manager.get("postgres.pool.max_size", 10)

        if cls._writer_pool is None:
            logger.info("Initializing writer DB pool")
            import asyncio
            for _ in range(30):
                try:
                    cls._writer_pool = await asyncpg.create_pool(dsn=dsn, min_size=min_size, max_size=max_size)
                    break
                except Exception as e:
                    logger.warning(f"Waiting for DB pool... {e}")
                    await asyncio.sleep(1)

        if cls._reader_pool is None:
            logger.info("Initializing reader DB pool")
            # In v1, reader points to the same DSN
            for _ in range(30):
                try:
                    cls._reader_pool = await asyncpg.create_pool(dsn=dsn, min_size=min_size, max_size=max_size)
                    break
                except Exception as e:
                    logger.warning(f"Waiting for DB pool... {e}")
                    await asyncio.sleep(1)

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
