"""E2E test fixtures with deterministic Docker service readiness."""

from __future__ import annotations

import asyncio
import json
import os
from urllib import request

import asyncpg
import pytest
import pytest_asyncio
import valkey.asyncio as avalkey

from libs.common.db.pool_manager import DBPoolManager


E2E_WAIT_ATTEMPTS = int(os.getenv("E2E_WAIT_ATTEMPTS", "60"))
E2E_WAIT_DELAY_SECONDS = float(os.getenv("E2E_WAIT_DELAY_SECONDS", "2"))
INGESTION_HEALTH_URL = os.getenv(
    "INGESTION_HEALTH_URL",
    "http://127.0.0.1:8002/health",
)


def _postgres_connection_kwargs() -> dict[str, object]:
    return {
        "user": os.getenv("POSTGRES_USER", "flipper"),
        "password": os.getenv("POSTGRES_PASSWORD", "flipperpass"),
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "database": os.getenv("POSTGRES_DB", "flipper_db"),
    }


class E2ERuntimeConfig:
    def get(self, key_path: str, default=None):
        postgres = _postgres_connection_kwargs()
        mapping = {
            "postgres.user": postgres["user"],
            "postgres.password": postgres["password"],
            "postgres.host": postgres["host"],
            "postgres.port": postgres["port"],
            "postgres.database": postgres["database"],
            "postgres.pool.min_size": 1,
            "postgres.pool.max_size": 2,
            "valkey.uri": os.getenv("VALKEY_URI", "redis://localhost:6380/0"),
            "ingestion.streams.runtime_status_maxlen": 5000,
            "ingestion.streams.runtime_status_approximate": True,
            "ingestion.observability.disconnect_window_seconds": 3600,
        }
        if key_path in mapping:
            return mapping[key_path]
        return default


async def _wait_for_postgres() -> None:
    last_error: Exception | None = None
    for attempt in range(1, E2E_WAIT_ATTEMPTS + 1):
        try:
            connection = await asyncpg.connect(**_postgres_connection_kwargs())
            await connection.close()
            return
        except Exception as exc:
            last_error = exc
            if attempt == E2E_WAIT_ATTEMPTS:
                break
            await asyncio.sleep(E2E_WAIT_DELAY_SECONDS)
    raise RuntimeError("PostgreSQL did not become ready for E2E tests") from last_error


async def _wait_for_valkey() -> None:
    uri = os.getenv("VALKEY_URI", "redis://localhost:6380/0")
    client = avalkey.Valkey.from_url(uri, decode_responses=True)
    last_error: Exception | None = None
    try:
        for attempt in range(1, E2E_WAIT_ATTEMPTS + 1):
            try:
                response = await client.ping()
                if response:
                    return
            except Exception as exc:
                last_error = exc
            if attempt == E2E_WAIT_ATTEMPTS:
                break
            await asyncio.sleep(E2E_WAIT_DELAY_SECONDS)
    finally:
        await client.aclose()
    raise RuntimeError("Valkey did not become ready for E2E tests") from last_error


def _healthcheck_ok() -> bool:
    with request.urlopen(INGESTION_HEALTH_URL, timeout=5) as response:
        if response.status != 200:
            return False
        payload = json.loads(response.read().decode("utf-8"))
        return payload.get("status") == "ok"


async def _wait_for_ingestion_health() -> None:
    last_error: Exception | None = None
    for attempt in range(1, E2E_WAIT_ATTEMPTS + 1):
        try:
            if await asyncio.to_thread(_healthcheck_ok):
                return
        except Exception as exc:
            last_error = exc
        if attempt == E2E_WAIT_ATTEMPTS:
            break
        await asyncio.sleep(E2E_WAIT_DELAY_SECONDS)
    raise RuntimeError("Ingestion runtime healthcheck did not become ready") from last_error


@pytest.fixture(autouse=True, scope="session")
def _reset_singletons():
    """Reset singletons before E2E session to avoid leftover unit-test state."""
    DBPoolManager._writer_pool = None
    DBPoolManager._reader_pool = None
    yield
    DBPoolManager._writer_pool = None
    DBPoolManager._reader_pool = None


@pytest_asyncio.fixture(scope="session", autouse=True)
async def docker_services_ready():
    """Wait until Docker-backed dependencies are reachable for direct pytest runs."""
    await _wait_for_postgres()
    await _wait_for_valkey()
    await _wait_for_ingestion_health()


@pytest_asyncio.fixture
async def db_pools():
    """Function-scoped DB pools pointing at the Docker TimescaleDB."""
    config = E2ERuntimeConfig()
    await DBPoolManager.init_pools(config_manager=config)
    yield
    await DBPoolManager.close_pools()
    DBPoolManager._writer_pool = None
    DBPoolManager._reader_pool = None


@pytest.fixture
def runtime_config():
    return E2ERuntimeConfig()


@pytest_asyncio.fixture
async def valkey_client():
    """Function-scoped Valkey client pointing at Docker broker."""
    uri = os.getenv("VALKEY_URI", "redis://localhost:6380/0")
    client = avalkey.Valkey.from_url(uri, decode_responses=True)
    yield client
    await client.aclose()
