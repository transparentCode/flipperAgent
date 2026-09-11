"""portfolio_app entrypoint — config/bootstrap around modular runtime."""

from __future__ import annotations

import os

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.constants import CONFIG_FILE_PORTFOLIO, CONFIG_FILE_MODELS
from libs.common.db.pool_manager import DBPoolManager
from libs.common.discovery import discover_assets, discover_asset_timeframes
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging

from apps.portfolio_app.portfolio_worker import PortfolioWorker
from apps.portfolio_app.runtime.mark_worker import PortfolioMarkWorker
from apps.portfolio_app.runtime.runner import (
    PortfolioRuntimeRunner,
    periodic_snapshot_loop,
    supervise_worker,
)
from libs.portfolio.state import PortfolioState

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


async def _supervise_worker(
    label: str,
    build_worker,
    redis_client,
    restart_delay_seconds: float = 5.0,
) -> None:
    """Compatibility wrapper for the modular runtime supervisor."""
    await supervise_worker(label, build_worker, redis_client, restart_delay_seconds)


async def _periodic_snapshot_loop(
    state: PortfolioState,
    db_pool,
    interval_seconds: float,
) -> None:
    """Compatibility wrapper for the modular periodic snapshot loop."""
    await periodic_snapshot_loop(state, db_pool, interval_seconds)


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
    asset_timeframes = discover_asset_timeframes(config_mgr)
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

    runtime = PortfolioRuntimeRunner(
        assets=assets,
        db_pool=db_pool,
        redis_client=redis_client,
        config_mgr=config_mgr,
        state=shared_state,
        worker_factory=lambda asset, pool, cfg, state: PortfolioWorker(
            asset=asset,
            db_pool=pool,
            config_mgr=cfg,
            shared_state=state,
        ),
        asset_timeframes=asset_timeframes,
        mark_worker_factory=lambda asset, timeframe, pool, cfg, state: PortfolioMarkWorker(
            asset=asset,
            timeframe=timeframe,
            db_pool=pool,
            config_mgr=cfg,
            shared_state=state,
        ),
        restart_delay_seconds=restart_delay_seconds,
        periodic_snapshot_seconds=periodic_snapshot_seconds,
        supervise_worker_fn=_supervise_worker,
        snapshot_loop_fn=_periodic_snapshot_loop,
    )

    try:
        await runtime.run()
    finally:
        await redis_client.aclose()
        await DBPoolManager.close_pools()


def main() -> None:
    import asyncio

    asyncio.run(_run())


if __name__ == "__main__":
    main()
