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
@patch("apps.execution_app.main.DBPoolManager")
@patch("apps.execution_app.main.persist_runtime_state", new_callable=AsyncMock)
@patch("apps.execution_app.main.build_shared_services", new_callable=AsyncMock)
@patch("apps.execution_app.main.bootstrap_execution_app", new_callable=AsyncMock)
async def test_run_spawns_supervised_workers_per_asset(
    mock_bootstrap_execution_app,
    mock_build_shared_services,
    mock_persist_runtime_state,
    MockPoolManager,
) -> None:
    from apps.execution_app.main import _run
    from apps.execution_app.bootstrap import ExecutionBootstrapContext

    redis_client = AsyncMock()
    config_mgr = MagicMock()
    writer_pool = object()
    mock_bootstrap_execution_app.return_value = ExecutionBootstrapContext(
        config_mgr=config_mgr,
        assets=["BTCUSDT", "ETHUSDT"],
        redis_client=redis_client,
        writer_pool=writer_pool,
        exec_config={
            "mode": "paper",
            "consumer_restart_delay_seconds": 0,
            "idempotency": {"persist_to_db": False, "max_memory_keys": 100},
            "paper": {"fill_delay_ms": 0, "slippage_jitter_bps": 0.0},
        },
        restart_delay_seconds=0,
    )
    mock_build_shared_services.return_value = MagicMock()
    MockPoolManager.close_pools = AsyncMock()

    with patch("apps.execution_app.main._supervise_worker", new_callable=AsyncMock) as mock_supervise:
        await _run()

    assert mock_supervise.await_count == 2
    mock_build_shared_services.assert_awaited_once_with(
        {
            "mode": "paper",
            "consumer_restart_delay_seconds": 0,
            "idempotency": {"persist_to_db": False, "max_memory_keys": 100},
            "paper": {"fill_delay_ms": 0, "slippage_jitter_bps": 0.0},
        },
        writer_pool=writer_pool,
        redis_client=redis_client,
    )
    mock_persist_runtime_state.assert_awaited_once()
    redis_client.aclose.assert_awaited_once()
