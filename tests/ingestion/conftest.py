import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from apps.ingestion_app.coordination import IngestionCoordinator

@pytest.fixture
def mock_asyncpg_pool():
    pool = MagicMock()
    conn = AsyncMock()
    # Support async with pool.acquire() as conn:
    ctx = AsyncMock()
    ctx.__aenter__.return_value = conn
    ctx.__aexit__.return_value = None
    pool.acquire.return_value = ctx
    return pool

@pytest.fixture
def mock_aiofiles():
    mock_file = AsyncMock()
    mock_open = AsyncMock()
    mock_open.return_value.__aenter__.return_value = mock_file
    return mock_open

@pytest.fixture
def mock_ccxt_adapter():
    adapter = AsyncMock()
    return adapter

@pytest.fixture(autouse=True)
def patch_db_pool_manager(mock_asyncpg_pool, mocker):
    mocker.patch(
        "apps.ingestion_app.orchestration.tasks.DBPoolManager.get_writer_pool",
        return_value=mock_asyncpg_pool
    )

@pytest.fixture
def base_worker_ctx(mock_asyncpg_pool, mock_ccxt_adapter):
    coordinator = MagicMock(spec=IngestionCoordinator)
    coordinator.transition = AsyncMock()
    return {
        "job_id": "test_job_123",
        "ccxt_adapter": mock_ccxt_adapter,
        "binance_adapter": AsyncMock(),
        "coordinator": coordinator,
    }