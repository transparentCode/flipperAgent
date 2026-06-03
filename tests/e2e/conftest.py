"""E2E test fixtures — assumes Docker containers are already running."""

from __future__ import annotations

import os
import asyncio

import pytest
import pytest_asyncio
import asyncpg
import valkey.asyncio as avalkey

from libs.common.db.pool_manager import DBPoolManager
from libs.common.config import ConfigManager


@pytest.fixture(autouse=True, scope="session")
def _reset_singletons():
    """Reset singletons before E2E session to avoid leftover unit-test state."""
    ConfigManager._instance = None
    DBPoolManager._writer_pool = None
    DBPoolManager._reader_pool = None
    yield
    ConfigManager._instance = None
    DBPoolManager._writer_pool = None
    DBPoolManager._reader_pool = None


@pytest_asyncio.fixture
async def db_pools():
    """Function-scoped DB pools pointing at the Docker TimescaleDB."""
    class E2EConfigManager(ConfigManager):
        def get(self, key_path: str, default=None):
            mapping = {
                "postgres.user": os.getenv("POSTGRES_USER", "flipper"),
                "postgres.password": os.getenv("POSTGRES_PASSWORD", "flipperpass"),
                "postgres.host": os.getenv("POSTGRES_HOST", "localhost"),
                "postgres.port": int(os.getenv("POSTGRES_PORT", "5432")),
                "postgres.database": os.getenv("POSTGRES_DB", "flipper_db"),
                "postgres.pool.min_size": 1,
                "postgres.pool.max_size": 2,
            }
            if key_path in mapping:
                return mapping[key_path]
            return super().get(key_path, default)

    config = E2EConfigManager()
    await DBPoolManager.init_pools(config_manager=config)
    yield
    await DBPoolManager.close_pools()
    DBPoolManager._writer_pool = None
    DBPoolManager._reader_pool = None


@pytest_asyncio.fixture
async def valkey_client():
    """Function-scoped Valkey client pointing at Docker broker."""
    uri = os.getenv("VALKEY_URI", "redis://localhost:6380/0")
    client = avalkey.Valkey.from_url(uri, decode_responses=True)
    yield client
    await client.aclose()
