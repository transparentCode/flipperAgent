"""Runtime supervision for execution_app."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.TRADE_EXECUTION)

BuildWorkerFn = Callable[[str], Any]
SuperviseWorkerFn = Callable[[str, Callable[[], Any], Any, int], Awaitable[None]]


async def supervise_worker(
    label: str,
    build_worker: Callable[[], Any],
    redis_client: Any,
    restart_delay_seconds: int = 5,
) -> None:
    while True:
        worker = build_worker()
        await worker.connect(redis_client)
        try:
            await worker.start()
            logger.error(
                "%s exited unexpectedly; restarting in %ss",
                label,
                restart_delay_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "%s crashed; restarting in %ss",
                label,
                restart_delay_seconds,
            )
        await asyncio.sleep(restart_delay_seconds)


class ExecutionRuntimeRunner:
    """Coordinates supervised per-asset execution workers."""

    def __init__(
        self,
        *,
        assets: list[str],
        redis_client: Any,
        restart_delay_seconds: int,
        worker_factory: BuildWorkerFn,
        supervise_worker_fn: SuperviseWorkerFn = supervise_worker,
    ) -> None:
        self.assets = assets
        self.redis_client = redis_client
        self.restart_delay_seconds = restart_delay_seconds
        self.worker_factory = worker_factory
        self.supervise_worker_fn = supervise_worker_fn

    async def run(self) -> None:
        tasks: list[asyncio.Task[Any]] = []
        try:
            for asset in self.assets:
                tasks.append(
                    asyncio.create_task(
                        self.supervise_worker_fn(
                            label=f"ExecutionWorker[{asset}]",
                            build_worker=lambda asset=asset: self.worker_factory(asset),
                            redis_client=self.redis_client,
                            restart_delay_seconds=self.restart_delay_seconds,
                        ),
                    ),
                )

            logger.info("Spawned %s execution workers", len(self.assets))
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            raise
