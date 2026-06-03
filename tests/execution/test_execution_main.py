from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _RestartingWorker:
    async def connect(self, redis_client) -> None:
        return None

    async def start(self) -> None:
        return None


@pytest.mark.asyncio
async def test_supervise_worker_restarts_after_unexpected_return() -> None:
    from apps.execution_app.main import _supervise_worker

    starts = 0
    connects = 0

    class _Worker:
        async def connect(self, redis_client):
            nonlocal connects
            connects += 1

        async def start(self):
            nonlocal starts
            starts += 1
            return None

    task = asyncio.create_task(
        _supervise_worker(
            label="fake",
            build_worker=_Worker,
            redis_client=object(),
            restart_delay_seconds=0,
        ),
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert starts >= 2
    assert connects >= 2


@pytest.mark.asyncio
@patch("apps.execution_app.main.configure_logging")
@patch("apps.execution_app.main.discover_assets")
@patch("apps.execution_app.main.create_valkey_client")
@patch("apps.execution_app.main.init_db_pools", new_callable=AsyncMock)
@patch("apps.execution_app.main.DBPoolManager")
@patch("apps.execution_app.main.ConfigManager")
async def test_run_spawns_supervised_workers_per_asset(
    MockConfigManager,
    MockPoolManager,
    _mock_init_db_pools,
    mock_create_valkey_client,
    mock_discover_assets,
    _mock_configure_logging,
) -> None:
    from apps.execution_app.main import _run

    redis_client = AsyncMock()
    mock_create_valkey_client.return_value = redis_client
    mock_discover_assets.return_value = ["BTCUSDT", "ETHUSDT"]

    cfg = MockConfigManager.return_value
    cfg.register_file = MagicMock()
    cfg.get.side_effect = lambda key, default=None: {
        "logging.level": "INFO",
        "execution": {
            "mode": "paper",
            "consumer_restart_delay_seconds": 0,
            "idempotency": {"persist_to_db": False, "max_memory_keys": 100},
            "paper": {"fill_delay_ms": 0, "slippage_jitter_bps": 0.0},
        },
    }.get(key, default)
    MockPoolManager.get_writer_pool.return_value = object()
    MockPoolManager.close_pools = AsyncMock()

    with patch("apps.execution_app.main._supervise_worker", new_callable=AsyncMock) as mock_supervise:
        await _run()

    assert mock_supervise.await_count == 2
    redis_client.aclose.assert_awaited_once()
