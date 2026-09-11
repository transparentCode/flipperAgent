"""Runtime orchestration for portfolio_app."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.portfolio.equity_curve import EquityCurveBuilder
from libs.portfolio.state import PortfolioState

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)

SuperviseWorkerFn = Callable[[str, Callable[[], Any], Any, float], Awaitable[None]]
SnapshotLoopFn = Callable[[PortfolioState, Any, float], Awaitable[None]]


async def supervise_worker(
    label: str,
    build_worker: Callable[[], Any],
    redis_client: Any,
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


async def periodic_snapshot_loop(
    state: PortfolioState,
    db_pool: Any,
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


class PortfolioRuntimeRunner:
    """Coordinates shared state, worker supervision, and portfolio snapshots."""

    def __init__(
        self,
        *,
        assets: list[str],
        db_pool: Any,
        redis_client: Any,
        config_mgr: Any,
        state: PortfolioState,
        worker_factory: Callable[[str, Any, Any, PortfolioState], Any],
        asset_timeframes: dict[str, list[str]] | None = None,
        mark_worker_factory: Callable[[str, str, Any, Any, PortfolioState], Any] | None = None,
        restart_delay_seconds: float,
        periodic_snapshot_seconds: float,
        supervise_worker_fn: SuperviseWorkerFn = supervise_worker,
        snapshot_loop_fn: SnapshotLoopFn = periodic_snapshot_loop,
    ) -> None:
        self.assets = assets
        self.db_pool = db_pool
        self.redis_client = redis_client
        self.config_mgr = config_mgr
        self.state = state
        self.worker_factory = worker_factory
        self.asset_timeframes = asset_timeframes or {}
        self.mark_worker_factory = mark_worker_factory
        self.restart_delay_seconds = restart_delay_seconds
        self.periodic_snapshot_seconds = periodic_snapshot_seconds
        self.supervise_worker_fn = supervise_worker_fn
        self.snapshot_loop_fn = snapshot_loop_fn

    async def run(self) -> None:
        """Start supervised per-asset workers plus the periodic snapshot loop."""
        tasks: list[asyncio.Task[Any]] = []
        try:
            for asset in self.assets:
                tasks.append(
                    asyncio.create_task(
                        self.supervise_worker_fn(
                            asset,
                            lambda asset=asset: self.worker_factory(
                                asset,
                                self.db_pool,
                                self.config_mgr,
                                self.state,
                            ),
                            self.redis_client,
                            self.restart_delay_seconds,
                        ),
                    ),
                )

            if self.mark_worker_factory is not None:
                for asset, timeframes in self.asset_timeframes.items():
                    for timeframe in timeframes:
                        tasks.append(
                            asyncio.create_task(
                                self.supervise_worker_fn(
                                    f"{asset}:{timeframe}",
                                    lambda asset=asset, timeframe=timeframe: self.mark_worker_factory(
                                        asset,
                                        timeframe,
                                        self.db_pool,
                                        self.config_mgr,
                                        self.state,
                                    ),
                                    self.redis_client,
                                    self.restart_delay_seconds,
                                ),
                            ),
                        )

            tasks.append(
                asyncio.create_task(
                    self.snapshot_loop_fn(
                        self.state,
                        self.db_pool,
                        self.periodic_snapshot_seconds,
                    ),
                ),
            )

            mark_worker_count = sum(len(timeframes) for timeframes in self.asset_timeframes.values())
            logger.info(
                "Spawned %s portfolio fill workers and %s mark workers",
                len(self.assets),
                mark_worker_count,
            )
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            raise
