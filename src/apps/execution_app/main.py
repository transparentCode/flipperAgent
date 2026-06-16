"""execution_app entrypoint — config/bootstrap around modular runtime."""

from __future__ import annotations

import asyncio
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

from apps.execution_app.bootstrap import bootstrap_execution_app
from apps.execution_app.factories import (
    build_shared_services,
    build_worker,
    persist_runtime_state,
)
from apps.execution_app.runtime.runner import (
    ExecutionRuntimeRunner,
    supervise_worker,
)

logger = bind_logger(__name__, system_component=SystemComponent.TRADE_EXECUTION)


async def _supervise_worker(
    label: str,
    build_worker,
    redis_client,
    restart_delay_seconds: int = 5,
) -> None:
    """Compatibility wrapper for the modular runtime supervisor."""
    await supervise_worker(label, build_worker, redis_client, restart_delay_seconds)


async def _run() -> None:
    context = await bootstrap_execution_app()
    if not context.assets or context.redis_client is None or context.writer_pool is None:
        return

    shared = await build_shared_services(
        context.exec_config,
        writer_pool=context.writer_pool,
        redis_client=context.redis_client,
    )
    runtime = ExecutionRuntimeRunner(
        assets=context.assets,
        redis_client=context.redis_client,
        restart_delay_seconds=context.restart_delay_seconds,
        worker_factory=lambda asset: build_worker(
            asset,
            shared=shared,
            exec_config=context.exec_config,
        ),
        supervise_worker_fn=_supervise_worker,
    )

    try:
        await runtime.run()
    finally:
        await persist_runtime_state(shared)
        await context.redis_client.aclose()
        await DBPoolManager.close_pools()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
