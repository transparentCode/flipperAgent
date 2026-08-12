"""signal_app entrypoint — boots modular runtime workers from config."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Callable

from apps.signal_app.catalog import SignalPairCatalog
from apps.signal_app.runtime.runner import SignalRuntimeRunner
from apps.signal_app.runtime_pairs import build_signal_pairs
from apps.signal_app.settings import SignalWorkerSettings
from libs.common.asset_manifest import AssetManifestStore
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.constants import CONFIG_FILE_FEATURES, CONFIG_FILE_MODELS
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging

logger = bind_logger(__name__, system_component=SystemComponent.SIGNAL_APP)


def _install_signal_handlers(shutdown_event: asyncio.Event) -> Callable[[], None]:
    """Install process shutdown handlers and return an idempotent remover."""
    loop = asyncio.get_running_loop()
    installed_signals: list[signal.Signals] = []

    def request_shutdown() -> None:
        if not shutdown_event.is_set():
            logger.info("Signal worker shutdown requested")
        shutdown_event.set()

    for shutdown_signal in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(shutdown_signal, request_shutdown)
        installed_signals.append(shutdown_signal)

    removed = False

    def remove_signal_handlers() -> None:
        nonlocal removed
        if removed:
            return
        removed = True
        for shutdown_signal in installed_signals:
            loop.remove_signal_handler(shutdown_signal)

    return remove_signal_handlers


async def _run_runner_until_shutdown(
    runner: SignalRuntimeRunner,
    shutdown_event: asyncio.Event,
) -> None:
    """Run the signal runtime until it exits or the process is asked to stop."""
    runner_task = asyncio.create_task(runner.start(), name="signal-runtime-runner")
    shutdown_task = asyncio.create_task(
        shutdown_event.wait(),
        name="signal-runtime-shutdown-waiter",
    )
    stop_called = False

    async def stop_once() -> None:
        nonlocal stop_called
        if stop_called:
            return
        stop_called = True
        await runner.stop()

    try:
        done, _ = await asyncio.wait(
            (runner_task, shutdown_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if shutdown_task in done:
            await stop_once()
            if not runner_task.done():
                runner_task.cancel()
            result = await asyncio.gather(runner_task, return_exceptions=True)
            runner_result = result[0]
            if isinstance(runner_result, BaseException) and not isinstance(
                runner_result, asyncio.CancelledError
            ):
                raise runner_result
        else:
            await runner_task
    finally:
        await stop_once()
        if not runner_task.done():
            runner_task.cancel()
        await asyncio.gather(runner_task, return_exceptions=True)
        shutdown_task.cancel()
        await asyncio.gather(shutdown_task, return_exceptions=True)


async def _run() -> None:
    config_mgr = ConfigManager()
    redis_client = None
    runner: SignalRuntimeRunner | None = None
    runner_lifecycle_started = False
    telemetry_initialized = False
    try:
        config_mgr.register_file(CONFIG_FILE_MODELS)
        config_mgr.register_file(CONFIG_FILE_FEATURES)

        try:
            from libs.common.telemetry.bootstrap import init_telemetry

            init_telemetry("signal_app")
            telemetry_initialized = True
        except ImportError:
            pass

        log_level = config_mgr.get("logging.level", default="INFO")
        configure_logging(
            level=log_level,
            enable_file_logging=True,
            console_format=os.environ.get("LOG_FORMAT", "json"),
            log_file=os.environ.get("LOG_FILE"),
        )
        try:
            from libs.common.telemetry.bootstrap import attach_otel_log_handler

            attach_otel_log_handler()
        except ImportError:
            pass

        await init_db_pools(config_mgr)
        redis_client = await create_valkey_client(config_mgr)
        full_catalog = SignalPairCatalog(config_manager=config_mgr)
        manifest_store = AssetManifestStore(redis_client)
        manifest_assets = await manifest_store.list_assets()
        resolved_pairs = build_signal_pairs(
            config_mgr,
            live_manifests=manifest_assets if manifest_assets else None,
        )
        if not resolved_pairs:
            logger.warning(
                "No asset/timeframe pairs found in canonical manifest or models.yaml. Exiting."
            )
            return

        runner = SignalRuntimeRunner(
            catalog=full_catalog,
            initial_pairs=resolved_pairs,
            worker_settings=SignalWorkerSettings.from_config(config_mgr),
        )
        logger.info(
            "Discovered %s signal asset/timeframe pairs from %s: %s",
            len(resolved_pairs),
            "asset manifest" if manifest_assets else "models.yaml",
            [
                (
                    pair.asset,
                    pair.timeframe,
                    pair.trigger_timeframe or pair.timeframe,
                    pair.trigger_mode,
                    pair.base_timeframe,
                    list(pair.required_context_profiles),
                )
                for pair in resolved_pairs
            ],
        )

        await runner.connect(redis_client)
        shutdown_event = asyncio.Event()
        remove_signal_handlers = _install_signal_handlers(shutdown_event)
        try:
            runner_lifecycle_started = True
            await _run_runner_until_shutdown(runner, shutdown_event)
            logger.info("Signal runtime stopped")
        finally:
            remove_signal_handlers()
    finally:
        if runner is not None and not runner_lifecycle_started:
            await runner.stop()
            logger.info("Signal runtime stopped before startup completed")
        if redis_client is not None:
            await redis_client.aclose()
            logger.info("Signal Valkey client closed")
        await DBPoolManager.close_pools()
        logger.info("Signal DB pools closed")
        config_mgr.shutdown()
        logger.info("Signal ConfigManager shut down")
        if telemetry_initialized:
            from libs.common.telemetry.bootstrap import shutdown_telemetry_nonblocking

            shutdown_telemetry_nonblocking()
            logger.info("Signal telemetry shut down")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
