"""Tests for libs.common.db.pool_manager — DBPoolManager."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from libs.common.db.pool_manager import DBPoolManager


@pytest.fixture(autouse=True)
def reset_pool_manager():
    DBPoolManager._writer_pool = None
    DBPoolManager._reader_pool = None
    # Reset the lock so tests don't interfere
    DBPoolManager._init_lock = asyncio.Lock()
    yield
    DBPoolManager._writer_pool = None
    DBPoolManager._reader_pool = None


class TestDBPoolManager:
    @pytest.mark.asyncio
    @patch("libs.common.db.pool_manager.asyncpg")
    async def test_init_pools_retries_on_failure(self, mock_asyncpg) -> None:
        """create_pool fails 2 times then succeeds → pools are created."""
        mock_pool = MagicMock()
        effects = [Exception("conn refused"), Exception("conn refused"), mock_pool]
        mock_asyncpg.create_pool = AsyncMock(side_effect=effects * 2)  # writer + reader

        mock_cfg = MagicMock()
        mock_cfg.get.return_value = None

        with patch("libs.common.db.pool_manager.os.getenv", return_value="postgres://host/db"):
            with patch("libs.common.db.pool_manager.asyncio.sleep", new_callable=AsyncMock):
                await DBPoolManager.init_pools(config_manager=mock_cfg)

        assert DBPoolManager._writer_pool is not None
        assert DBPoolManager._reader_pool is not None

    @pytest.mark.asyncio
    @patch("libs.common.db.pool_manager.asyncpg")
    async def test_init_pools_raises_after_max_retries(self, mock_asyncpg) -> None:
        """create_pool always fails → RuntimeError raised."""
        mock_asyncpg.create_pool = AsyncMock(side_effect=Exception("always fail"))

        mock_cfg = MagicMock()
        mock_cfg.get.return_value = None

        with patch("libs.common.db.pool_manager.os.getenv", return_value="postgres://host/db"):
            with patch("libs.common.db.pool_manager.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(RuntimeError, match="Failed to connect to writer database"):
                    await DBPoolManager.init_pools(config_manager=mock_cfg)

    @pytest.mark.asyncio
    @patch("libs.common.db.pool_manager.asyncpg")
    async def test_double_init_is_noop(self, mock_asyncpg) -> None:
        """Second init_pools call should be a no-op (early return)."""
        mock_pool = MagicMock()
        mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

        mock_cfg = MagicMock()
        mock_cfg.get.return_value = None

        with patch("libs.common.db.pool_manager.os.getenv", return_value="postgres://host/db"):
            await DBPoolManager.init_pools(config_manager=mock_cfg)
            call_count_after_first = mock_asyncpg.create_pool.call_count

            await DBPoolManager.init_pools(config_manager=mock_cfg)
            call_count_after_second = mock_asyncpg.create_pool.call_count

        # No additional create_pool calls on the second init
        assert call_count_after_second == call_count_after_first
