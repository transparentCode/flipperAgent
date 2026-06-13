from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from arq.connections import create_pool
from fastapi import FastAPI

from apps.ingestion_app.bootstrap import (
    build_redis_settings,
    create_runtime_coordinator,
    initialize_storage,
)
from apps.ingestion_app.runtime.reconciler import IngestionRuntimeReconciler
from apps.ingestion_app.runtime.shared import config_manager, logger, track_task
from libs.common.db.pool_manager import DBPoolManager


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Initializing DB pools...")
    arq_pool = None
    redis_client = None

    try:
        await initialize_storage(config_manager)
        logger.info("Connecting to ARQ redis...")
        arq_pool = await create_pool(build_redis_settings(config_manager))
        redis_client, coordinator = await create_runtime_coordinator(config_manager)
    except Exception:
        if arq_pool is not None:
            await arq_pool.close()
        if redis_client is not None:
            await redis_client.aclose()
        await DBPoolManager.close_pools()
        raise

    background_tasks: set[asyncio.Task[Any]] = set()
    reconciler = IngestionRuntimeReconciler(
        config_manager=config_manager,
        arq_pool=arq_pool,
        coordinator=coordinator,
        redis_client=redis_client,
    )

    await reconciler.reconcile_once()
    reconciler_task = track_task(background_tasks, asyncio.create_task(reconciler.run()))

    yield

    logger.info("Shutting down... Cleaning up.")
    reconciler_task.cancel()
    await reconciler.stop()
    for task in list(background_tasks):
        task.cancel()
    if background_tasks:
        await asyncio.gather(*background_tasks, return_exceptions=True)
    await DBPoolManager.close_pools()
    if arq_pool is not None:
        await arq_pool.close()
    if redis_client is not None:
        await redis_client.aclose()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
