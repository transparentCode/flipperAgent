from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.ingestion_app.main import main
from apps.ingestion_app.schedules import IngestionScheduler
from apps.ingestion_app.worker import WorkerSettings, shutdown, startup


@pytest.mark.asyncio
async def test_worker_startup_loads_context() -> None:
    ctx: dict[str, object] = {}

    with (
        patch("apps.ingestion_app.worker.populate_worker_context", new=AsyncMock()) as mock_populate,
    ):
        await startup(ctx)

    mock_populate.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_shutdown_closes_context() -> None:
    ccxt_adapter = AsyncMock()
    valkey_client = AsyncMock()
    ctx = {"ccxt_adapter": ccxt_adapter, "valkey_client": valkey_client}

    with patch("apps.ingestion_app.worker.cleanup_worker_context", new=AsyncMock()) as mock_cleanup:
        await shutdown(ctx)

    mock_cleanup.assert_awaited_once_with(ctx)


@pytest.mark.asyncio
async def test_worker_startup_rolls_back_resources_on_failure() -> None:
    ctx: dict[str, object] = {}

    with (
        patch(
            "apps.ingestion_app.worker.populate_worker_context",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
        patch("apps.ingestion_app.worker.cleanup_worker_context", new=AsyncMock()) as mock_cleanup,
    ):
        with pytest.raises(RuntimeError):
            await startup(ctx)

    mock_cleanup.assert_awaited_once_with(ctx)


def test_worker_settings_include_v2_jobs() -> None:
    func_names = [func.__name__ for func in WorkerSettings.functions]
    assert "poll_l2_depth" in func_names
    assert "run_rest_gap_fill" in func_names
    assert "purge_removed_asset" in func_names


def test_schedule_has_l2_cron_v2() -> None:
    scheduler = IngestionScheduler()
    jobs = scheduler.get_cron_jobs()
    job_funcs = [job.coroutine.__name__ for job in jobs]
    assert "poll_l2_depth" in job_funcs
    assert "scheduled_gap_fill" in job_funcs
    assert "scheduled_asset_cleanup" in job_funcs


def test_main_runs_v2_runtime_app() -> None:
    with (
        patch("apps.ingestion_app.main.ConfigManager") as mock_config_class,
        patch("apps.ingestion_app.main.configure_logging"),
        patch("apps.ingestion_app.main.bind_logger") as mock_bind_logger,
        patch("apps.ingestion_app.main.uvicorn.run") as mock_uvicorn_run,
        patch("libs.common.telemetry.bootstrap.init_telemetry"),
        patch("libs.common.telemetry.bootstrap.attach_otel_log_handler"),
    ):
        mock_config = mock_config_class.return_value
        mock_config.get.side_effect = lambda key, default=None: {
            "logging.level": "INFO",
            "logging.console_format": "json",
            "logging.log_file": None,
            "ingestion.server.host": "127.0.0.1",
            "ingestion.server.port": 9001,
        }.get(key, default)

        main()

    mock_bind_logger.return_value.info.assert_called_once_with(
        "Starting Ingestion controller on 127.0.0.1:9001"
    )
    mock_uvicorn_run.assert_called_once_with(
        "apps.ingestion_app.runtime.app:app",
        host="127.0.0.1",
        port=9001,
    )
