"""portfolio_app entrypoint — discovers assets, spawns PortfolioWorker(s)."""

from __future__ import annotations

import asyncio
import os
import time

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.constants import CONFIG_FILE_PORTFOLIO, CONFIG_FILE_MODELS
from libs.common.db.pool_manager import DBPoolManager
from libs.common.discovery import discover_assets
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging

from apps.portfolio_app.portfolio_worker import PortfolioWorker
from libs.portfolio.equity_curve import EquityCurveBuilder
from libs.portfolio.state import PortfolioState

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


async def _supervise_worker(
    label: str,
    build_worker,
    redis_client,
    restart_delay_seconds: float = 5.0,
) -> None:
    """Restart a portfolio worker if its consumer loop exits unexpectedly."""
    while True:
        worker = build_worker()
        await worker.connect(redis_client)
        try:
            await worker.start()
            logger.warning(
                "Portfolio worker %s exited unexpectedly; restarting in %.1fs",
                label,
                restart_delay_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Portfolio worker %s crashed; restarting in %.1fs",
                label,
                restart_delay_seconds,
            )
        await asyncio.sleep(restart_delay_seconds)


async def _periodic_snapshot_loop(
    state: PortfolioState,
    db_pool,
    interval_seconds: float,
) -> None:
    """Refresh risk-position marks and persist portfolio-wide equity snapshots."""
    builder = EquityCurveBuilder(db_pool)
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await state.sync_marks_from_risk_positions(db_pool)
            async with state.lock:
                point, net_exposure_pct, gross_exposure_pct = state.build_equity_snapshot(
                    timestamp=time.time(),
                )
            await builder.save_equity_point(point, net_exposure_pct, gross_exposure_pct)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Portfolio periodic snapshot loop failed; continuing")


async def _run() -> None:
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_PORTFOLIO)
    config_mgr.register_file(CONFIG_FILE_MODELS)

    try:
        from libs.common.telemetry.bootstrap import init_telemetry
        init_telemetry("portfolio_app")
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

    assets = discover_assets(config_mgr)
    logger.info(f"Portfolio tracker assets: {assets}")

    # --- Connection setup ---
    await init_db_pools(config_mgr)
    redis_client = await create_valkey_client(config_mgr)
    db_pool = DBPoolManager.get_writer_pool()
    portfolio_cfg = config_mgr.get("portfolio", {})
    consumer_cfg = portfolio_cfg.get("consumer", {})
    initial_balance = portfolio_cfg.get("initial_balance", 10_000.0)
    restart_delay_seconds = consumer_cfg.get("restart_delay_seconds", 5)
    periodic_snapshot_seconds = consumer_cfg.get("periodic_snapshot_seconds", 60)
    shared_state = await PortfolioState.load(db_pool, initial_balance)

    try:
        tasks: list[asyncio.Task] = []
        for asset in assets:
            tasks.append(
                asyncio.create_task(
                    _supervise_worker(
                        label=asset,
                        build_worker=lambda asset=asset: PortfolioWorker(
                            asset=asset,
                            db_pool=db_pool,
                            config_mgr=config_mgr,
                            shared_state=shared_state,
                        ),
                        redis_client=redis_client,
                        restart_delay_seconds=restart_delay_seconds,
                    ),
                ),
            )

        tasks.append(
            asyncio.create_task(
                _periodic_snapshot_loop(
                    shared_state,
                    db_pool,
                    periodic_snapshot_seconds,
                ),
            ),
        )

        logger.info(f"Spawned {len(assets)} portfolio workers")

        await asyncio.gather(*tasks)
    except BaseException:
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        raise
    finally:
        await redis_client.aclose()
        await DBPoolManager.close_pools()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
