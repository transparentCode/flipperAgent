"""Tests for libs.common.db.pool_manager — DBPoolManager."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from libs.common.db.pool_manager import DBPoolManager


@pytest.fixture(autouse=True)
def reset_pool_manager():
    DBPoolManager._writer_pool = None
    DBPoolManager._reader_pool = None
    # Reset the lock so tests don't interfere
    DBPoolManager._init_lock = asyncio.Lock()
    DBPoolManager._retained_cleanup_tasks.clear()
    yield
    DBPoolManager._writer_pool = None
    DBPoolManager._reader_pool = None
    DBPoolManager._retained_cleanup_tasks.clear()


class TestDBPoolManager:
    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    @pytest.mark.asyncio
    async def test_connect_timeout_rejects_non_finite_values(self, value) -> None:
        with pytest.raises(ValueError, match="finite"):
            await DBPoolManager.init_pools(connect_timeout=value)

    @pytest.mark.asyncio
    async def test_decision_opt_in_does_not_erase_preexisting_partial_pool(
        self,
    ) -> None:
        borrowed_writer = MagicMock()
        DBPoolManager._writer_pool = borrowed_writer
        with pytest.raises(RuntimeError, match="ownership"):
            await DBPoolManager.init_pools(return_created=True, cleanup_timeout=0.01)
        assert DBPoolManager._writer_pool is borrowed_writer
        borrowed_writer.close.assert_not_called()

    @pytest.mark.asyncio
    @patch("libs.common.db.pool_manager.asyncpg")
    async def test_default_init_preserves_cancellation_without_partial_cleanup(
        self,
        mock_asyncpg,
    ) -> None:
        started = asyncio.Event()
        writer_pool = MagicMock()
        writer_pool.close = AsyncMock()
        calls = 0

        async def blocked_create_pool(**_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return writer_pool
            started.set()
            await asyncio.Event().wait()

        mock_asyncpg.create_pool = blocked_create_pool
        with (
            patch(
                "libs.common.db.pool_manager.os.getenv",
                return_value="postgres://host/db",
            ),
        ):
            task = asyncio.create_task(DBPoolManager.init_pools())
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert DBPoolManager._writer_pool is writer_pool
        writer_pool.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_decision_partial_cleanup_is_bounded_and_retains_owner_task(
        self,
    ) -> None:
        release = asyncio.Event()
        close_started = asyncio.Event()

        async def close() -> None:
            close_started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()

        owned_writer = MagicMock()
        owned_writer.close = close
        owned_writer.terminate = MagicMock()
        DBPoolManager._writer_pool = owned_writer
        started = asyncio.get_running_loop().time()
        await DBPoolManager._reset_partial_state(cleanup_timeout=0.01)
        elapsed = asyncio.get_running_loop().time() - started
        assert close_started.is_set()
        assert elapsed < 0.08
        assert owned_writer.terminate.call_count == 1
        assert DBPoolManager._writer_pool is None
        assert DBPoolManager._retained_cleanup_tasks
        release.set()
        await asyncio.gather(*tuple(DBPoolManager._retained_cleanup_tasks))
        await asyncio.sleep(0)
        assert not DBPoolManager._retained_cleanup_tasks

    @pytest.mark.asyncio
    async def test_decision_partial_cleanup_uses_one_aggregate_budget(self) -> None:
        release = asyncio.Event()
        started: set[str] = set()

        async def close(name: str) -> None:
            started.add(name)
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()

        writer_pool = MagicMock()
        writer_pool.close = lambda: close("writer")
        writer_pool.terminate = MagicMock()
        reader_pool = MagicMock()
        reader_pool.close = lambda: close("reader")
        reader_pool.terminate = MagicMock()
        DBPoolManager._writer_pool = writer_pool
        DBPoolManager._reader_pool = reader_pool
        owner_tasks: set[asyncio.Task[object]] = set()

        started_at = asyncio.get_running_loop().time()
        await DBPoolManager._reset_partial_state(
            cleanup_timeout=0.01,
            owner_tasks=owner_tasks,
        )
        elapsed = asyncio.get_running_loop().time() - started_at

        assert elapsed < 0.08
        assert started == {"writer", "reader"}
        assert writer_pool.terminate.call_count == 1
        assert reader_pool.terminate.call_count == 1
        assert DBPoolManager._writer_pool is None
        assert DBPoolManager._reader_pool is None
        pending = tuple(owner_tasks)
        release.set()
        await asyncio.gather(*pending)
        await asyncio.sleep(0)
        assert not owner_tasks
        assert not DBPoolManager._retained_cleanup_tasks

    @pytest.mark.asyncio
    async def test_decision_partial_cleanup_uses_owner_remaining_callback(self) -> None:
        async def close() -> None:
            await asyncio.sleep(0.1)

        owned_writer = MagicMock()
        owned_writer.close = close
        owned_writer.terminate = MagicMock()
        DBPoolManager._writer_pool = owned_writer

        started_at = asyncio.get_running_loop().time()
        await DBPoolManager._reset_partial_state(
            cleanup_timeout=1.0,
            cleanup_remaining=lambda: 0.01,
        )
        elapsed = asyncio.get_running_loop().time() - started_at

        assert elapsed < 0.08
        assert owned_writer.terminate.call_count == 1
        assert DBPoolManager._writer_pool is None

    @pytest.mark.asyncio
    async def test_installed_asyncpg_blackhole_obeys_connect_timeout(self) -> None:
        requests: list[bytes] = []
        writers: list[asyncio.StreamWriter] = []
        stop = asyncio.Event()

        async def blackhole(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            writers.append(writer)
            try:
                requests.append(await asyncio.wait_for(reader.read(128), 0.2))
                await stop.wait()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(blackhole, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            started = asyncio.get_running_loop().time()
            with pytest.raises(Exception) as caught:
                await asyncpg.connect(
                    host="127.0.0.1",
                    port=port,
                    user="probe",
                    database="probe",
                    timeout=0.05,
                )
            elapsed = asyncio.get_running_loop().time() - started
        finally:
            stop.set()
            for writer in writers:
                writer.close()
            await asyncio.gather(
                *(writer.wait_closed() for writer in writers),
                return_exceptions=True,
            )
            server.close()
            await server.wait_closed()

        assert elapsed < 0.5
        assert requests
        assert isinstance(caught.value, (TimeoutError, OSError, asyncpg.PostgresError))

    @pytest.mark.asyncio
    @patch("libs.common.db.pool_manager.asyncpg")
    async def test_init_pools_retries_on_failure(self, mock_asyncpg) -> None:
        """create_pool fails 2 times then succeeds → pools are created."""
        mock_pool = MagicMock()
        effects = [Exception("conn refused"), Exception("conn refused"), mock_pool]
        mock_asyncpg.create_pool = AsyncMock(side_effect=effects * 2)  # writer + reader

        mock_cfg = MagicMock()
        mock_cfg.get.return_value = None

        with (
            patch(
                "libs.common.db.pool_manager.os.getenv",
                return_value="postgres://host/db",
            ),
            patch("libs.common.db.pool_manager.asyncio.sleep", new_callable=AsyncMock),
        ):
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

        with (
            patch(
                "libs.common.db.pool_manager.os.getenv",
                return_value="postgres://host/db",
            ),
            patch("libs.common.db.pool_manager.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(RuntimeError, match="Failed to connect to writer database"),
        ):
            await DBPoolManager.init_pools(config_manager=mock_cfg)

    @pytest.mark.asyncio
    @patch("libs.common.db.pool_manager.asyncpg")
    async def test_double_init_is_noop(self, mock_asyncpg) -> None:
        """Second init_pools call should be a no-op (early return)."""
        mock_pool = MagicMock()
        mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

        mock_cfg = MagicMock()
        mock_cfg.get.return_value = None

        with patch(
            "libs.common.db.pool_manager.os.getenv", return_value="postgres://host/db"
        ):
            await DBPoolManager.init_pools(config_manager=mock_cfg)
            call_count_after_first = mock_asyncpg.create_pool.call_count

            await DBPoolManager.init_pools(config_manager=mock_cfg)
            call_count_after_second = mock_asyncpg.create_pool.call_count

        # No additional create_pool calls on the second init
        assert call_count_after_second == call_count_after_first

    @pytest.mark.asyncio
    @patch("libs.common.db.pool_manager.asyncpg")
    async def test_reader_init_failure_resets_partial_state(self, mock_asyncpg) -> None:
        """A reader-pool failure should not leave a poisoned writer-only state."""
        writer_pool = AsyncMock()
        writer_pool.close = AsyncMock()
        replacement_writer_pool = MagicMock()
        replacement_reader_pool = MagicMock()

        mock_asyncpg.create_pool = AsyncMock(
            side_effect=[
                writer_pool,
                *([Exception("reader fail")] * 30),
                replacement_writer_pool,
                replacement_reader_pool,
            ]
        )

        mock_cfg = MagicMock()
        mock_cfg.get.return_value = None

        with (
            patch(
                "libs.common.db.pool_manager.os.getenv",
                return_value="postgres://host/db",
            ),
            patch("libs.common.db.pool_manager.asyncio.sleep", new_callable=AsyncMock),
        ):
            with pytest.raises(
                RuntimeError, match="Failed to connect to reader database"
            ):
                await DBPoolManager.init_pools(config_manager=mock_cfg)

            assert DBPoolManager._writer_pool is None
            assert DBPoolManager._reader_pool is None
            writer_pool.close.assert_awaited_once()

            await DBPoolManager.init_pools(config_manager=mock_cfg)

        assert DBPoolManager._writer_pool is replacement_writer_pool
        assert DBPoolManager._reader_pool is replacement_reader_pool
