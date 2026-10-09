"""Runnable v2 collector process: ``python -m apps.scraper_app.main``."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from datetime import UTC, datetime
from functools import partial

import asyncpg
import uvicorn

from apps.scraper_app.adapters.coinglass.client import CoinGlassClient
from apps.scraper_app.adapters.coinglass.cookies import CookieStore
from apps.scraper_app.adapters.tradingview.client import TradingViewClient
from apps.scraper_app.http_api.app import create_app
from apps.scraper_app.http_api.auth import token_source_from_environment
from apps.scraper_app.http_api.catalog import build_catalog
from apps.scraper_app.http_api.v2 import ApiDependencies
from apps.scraper_app.runtime.coinglass import CoinGlassLane
from apps.scraper_app.runtime.collector import Collector
from apps.scraper_app.runtime.purge import PurgeTask, retention_days
from apps.scraper_app.runtime.scheduler import Scheduler
from apps.scraper_app.runtime.singleton import AdvisoryLock
from apps.scraper_app.runtime.status import (
    CoinGlassReadiness,
    PurgeState,
    ReadinessReporter,
    ReadinessService,
    RuntimeState,
    compute_readiness,
)
from apps.scraper_app.settings import (
    ScraperSettings,
    database_uri,
    load_settings,
    purge_database_uri,
)
from apps.scraper_app.storage.repository import (
    PostgresPurgeRepository,
    PostgresScraperRepository,
)
from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging
from libs.common.telemetry.bootstrap import (
    attach_otel_log_handler,
    init_telemetry,
    shutdown_telemetry_nonblocking,
)

logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)

EXIT_LOCK_NOT_ACQUIRED = 2
EXIT_SCHEMA_MISSING = 3
EXIT_COLLECTOR_STOPPED = 4

BOOTSTRAP_COMMAND = "python -m apps.scraper_app.storage.bootstrap"


def utc_now() -> datetime:
    return datetime.now(UTC)


async def schema_is_applied(pool: asyncpg.Pool, *, coinglass: bool = False) -> bool:
    """The payload table is required only when the CoinGlass lane is configured."""
    query = (
        "SELECT to_regclass('scraper.reads') IS NOT NULL "
        "AND to_regclass('scraper.bar_observations') IS NOT NULL"
    )
    if coinglass:
        query += " AND to_regclass('scraper.payload_observations') IS NOT NULL"
    async with pool.acquire() as connection:
        return bool(await connection.fetchval(query))


async def serve(settings: ScraperSettings, uri: str) -> int:
    """Run the collector until shutdown; returns the process exit code."""
    db = settings.database
    pool = await asyncpg.create_pool(
        uri,
        min_size=1,
        max_size=3,
        timeout=db.connect_timeout_seconds,
        command_timeout=db.command_timeout_seconds,
    )
    lock = AdvisoryLock(
        partial(
            asyncpg.connect,
            uri,
            timeout=db.connect_timeout_seconds,
            command_timeout=db.command_timeout_seconds,
        ),
        probe_timeout_seconds=db.command_timeout_seconds,
    )
    tasks: list[asyncio.Task[None]] = []
    purge_pool: asyncpg.Pool | None = None
    api_pool: asyncpg.Pool | None = None
    try:
        if not await schema_is_applied(pool, coinglass=settings.coinglass is not None):
            logger.error(
                "schema 'scraper' is missing; run the operator step: %s",
                BOOTSTRAP_COMMAND,
            )
            return EXIT_SCHEMA_MISSING
        if not await lock.try_acquire():
            logger.error("another collector instance holds the advisory lock; exiting")
            return EXIT_LOCK_NOT_ACQUIRED

        logger.info(
            "advisory lock acquired; schema 'scraper' present; starting scheduler"
        )
        specs = settings.dataset_specs()
        repository = PostgresScraperRepository(pool, {s.id: s for s in specs})
        state = RuntimeState()
        collector = Collector(
            client=TradingViewClient(settings.tradingview),
            repository=repository,
            settings=settings.tradingview,
            clock=utc_now,
            retention_days=(
                settings.retention.tradingview_days
                if settings.retention is not None and settings.retention.enabled
                else None
            ),
        )
        scheduler = Scheduler(
            specs=specs,
            collector=collector,
            tradingview=settings.tradingview,
            schedule=settings.schedule,
            state=state,
            clock=utc_now,
            can_write=lambda: lock.held,
        )

        lane: CoinGlassLane | None = None
        coinglass_readiness: CoinGlassReadiness | None = None
        if settings.coinglass is not None:
            cg = settings.coinglass
            cookies = CookieStore(cg.cookies_path)
            lane = CoinGlassLane(
                specs=settings.payload_specs(),
                client=CoinGlassClient(cg, cookies=cookies, clock=utc_now),
                repository=repository,
                settings=cg,
                state=state,
                cookies=cookies,
                clock=utc_now,
                can_write=lambda: lock.held,
            )
            coinglass_readiness = CoinGlassReadiness(
                dataset_ids=tuple(s.id for s in settings.payload_specs()),
                max_read_age_seconds=cg.readiness.max_read_age_seconds,
            )

        purge_task: PurgeTask | None = None
        retention = settings.retention
        if retention is not None:
            purge_uri = purge_database_uri() if retention.enabled else None
            state.purge = PurgeState(
                enabled=retention.enabled,
                configured=purge_uri is not None or not retention.enabled,
                retention_days=retention_days(retention),
                max_age_seconds=retention.readiness_max_age_seconds,
            )
            if retention.enabled and purge_uri is None:
                logger.error(
                    "retention is enabled but SCRAPER_PURGE_POSTGRES_URI is not set; "
                    "the purge task is not started (collection continues)"
                )
            elif purge_uri is not None:
                # min_size=0: a purge-role problem surfaces as a failed pass,
                # never as a collector start failure.
                purge_pool = await asyncpg.create_pool(
                    purge_uri,
                    min_size=0,
                    max_size=2,
                    timeout=db.connect_timeout_seconds,
                    command_timeout=db.command_timeout_seconds,
                )
                purge_task = PurgeTask(
                    repository=PostgresPurgeRepository(purge_pool),
                    settings=retention,
                    tradingview_ids=tuple(s.id for s in specs),
                    coinglass_ids=tuple(s.id for s in settings.payload_specs()),
                    state=state.purge,
                    clock=utc_now,
                    can_write=lambda: lock.held,
                )

        reporter = ReadinessReporter()

        def compute():
            return compute_readiness(
                specs=specs,
                repository=repository,
                state=state,
                lock_held=lambda: lock.held,
                clock=utc_now,
                max_read_age_seconds=settings.readiness.max_read_age_seconds,
                latest_bar_grace_seconds=settings.readiness.latest_bar_grace_seconds,
                recent_gap_window_seconds=settings.readiness.recent_gap_window_seconds,
                max_clock_skew_seconds=settings.readiness.max_clock_skew_seconds,
                probe_timeout_seconds=settings.readiness.probe_timeout_seconds,
                reporter=reporter,
                coinglass=coinglass_readiness,
            )

        readiness = ReadinessService(compute)

        api_deps: ApiDependencies | None = None
        api = settings.api
        if api is not None and api.enabled:
            # Own read-only pool (min 0): API load never takes a collector,
            # readiness or purge connection.
            api_pool = await asyncpg.create_pool(
                uri,
                min_size=0,
                max_size=api.pool_max_size,
                timeout=db.connect_timeout_seconds,
                command_timeout=api.query_timeout_seconds,
                server_settings={
                    "application_name": "scraper_api",
                    "default_transaction_read_only": "on",
                    "statement_timeout": str(int(api.query_timeout_seconds * 1000)),
                },
            )
            api_deps = ApiDependencies(
                repository=PostgresScraperRepository(
                    api_pool, {s.id: s for s in specs}
                ),
                catalog=build_catalog(settings),
                settings=api,
                tokens=token_source_from_environment(),
                disabled=lambda: state.coinglass_disabled,
            )

        server = uvicorn.Server(
            uvicorn.Config(
                create_app(readiness=readiness, api=api_deps),
                host=settings.server.host,
                port=settings.server.port,
                log_config=None,
            )
        )

        def _on_background_done(task: asyncio.Task[None]) -> None:
            if not task.cancelled():
                logger.error(
                    "collector background task stopped", exc_info=task.exception()
                )
                server.should_exit = True

        tasks = [
            asyncio.create_task(scheduler.run(), name="scraper-scheduler"),
            asyncio.create_task(lock.supervise(), name="scraper-lock"),
        ]
        if lane is not None:
            tasks.append(asyncio.create_task(lane.run(), name="scraper-coinglass"))
        if purge_task is not None:
            tasks.append(asyncio.create_task(purge_task.run(), name="scraper-purge"))
        for task in tasks:
            task.add_done_callback(_on_background_done)

        await server.serve()
        return (
            EXIT_COLLECTOR_STOPPED
            if any(t.done() and not t.cancelled() for t in tasks)
            else 0
        )
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await lock.release()
        if purge_pool is not None:
            await purge_pool.close()
        if api_pool is not None:
            await api_pool.close()
        await pool.close()


def main() -> None:
    config_manager = ConfigManager()
    telemetry_initialized = False
    exit_code = 1
    try:
        settings = load_settings(config_manager)
        uri = database_uri()
        try:
            init_telemetry("scraper")
            telemetry_initialized = True
        except Exception:  # noqa: BLE001 - telemetry is non-authoritative
            telemetry_initialized = False
        configure_logging(
            level=config_manager.get("logging.level", default="INFO"),
            enable_file_logging=True,
            console_format=config_manager.get("logging.console_format", "json"),
            log_file=config_manager.get("logging.log_file"),
        )
        if telemetry_initialized:
            attach_otel_log_handler()
        logger.info(
            "Starting scraper collector on %s:%s with %d datasets",
            settings.server.host,
            settings.server.port,
            len(settings.datasets),
        )
        exit_code = asyncio.run(serve(settings, uri))
    finally:
        config_manager.shutdown()
        if telemetry_initialized:
            shutdown_telemetry_nonblocking()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()


__all__ = ["main", "serve"]
