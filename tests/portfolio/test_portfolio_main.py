from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_supervise_worker_restarts_after_unexpected_return() -> None:
    from apps.portfolio_app.main import _supervise_worker

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
@patch("apps.portfolio_app.main.configure_logging")
@patch("apps.portfolio_app.main.discover_assets")
@patch("apps.portfolio_app.main.create_valkey_client")
@patch("apps.portfolio_app.main.init_db_pools", new_callable=AsyncMock)
@patch("apps.portfolio_app.main.DBPoolManager")
@patch("apps.portfolio_app.main.PortfolioState")
@patch("apps.portfolio_app.main.ConfigManager")
async def test_run_spawns_supervised_workers_and_snapshot_loop(
    MockConfigManager,
    MockPortfolioState,
    MockPoolManager,
    _mock_init_db_pools,
    mock_create_valkey_client,
    mock_discover_assets,
    _mock_configure_logging,
) -> None:
    from apps.portfolio_app.main import _run

    redis_client = AsyncMock()
    mock_create_valkey_client.return_value = redis_client
    mock_discover_assets.return_value = ["BTCUSDT", "ETHUSDT"]

    cfg = MockConfigManager.return_value
    cfg.register_file = MagicMock()
    cfg.get.side_effect = lambda key, default=None: {
        "logging.level": "INFO",
        "portfolio": {
            "initial_balance": 10000.0,
            "consumer": {
                "restart_delay_seconds": 0,
                "periodic_snapshot_seconds": 60,
            },
        },
    }.get(key, default)

    MockPoolManager.get_writer_pool.return_value = object()
    MockPoolManager.close_pools = AsyncMock()
    MockPortfolioState.load = AsyncMock(return_value=MagicMock())

    with patch("apps.portfolio_app.main._supervise_worker", new_callable=AsyncMock) as mock_supervise, patch(
        "apps.portfolio_app.main._periodic_snapshot_loop",
        new_callable=AsyncMock,
    ) as mock_snapshot_loop:
        await _run()

    assert mock_supervise.await_count == 2
    mock_snapshot_loop.assert_awaited_once()
    redis_client.aclose.assert_awaited_once()
