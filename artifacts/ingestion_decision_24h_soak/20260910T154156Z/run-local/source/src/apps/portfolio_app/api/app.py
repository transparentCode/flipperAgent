"""Internal FastAPI application for portfolio observability."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from apps.portfolio_app.api.routes import router
from apps.portfolio_app.observability import PortfolioObservabilityService
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.db.pool_manager import DBPoolManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_mgr = ConfigManager()
    owns_valkey = False
    owns_db = False

    redis_client: Any | None = getattr(app.state, "redis_client", None)
    if redis_client is None:
        try:
            redis_client = await create_valkey_client(config_mgr)
            owns_valkey = True
        except Exception:
            redis_client = None

    db_pool = getattr(app.state, "db_pool", None)
    if db_pool is None:
        await init_db_pools(config_mgr)
        db_pool = DBPoolManager.get_reader_pool()
        owns_db = True

    service = getattr(app.state, "observability_service", None)
    if service is None:
        service = PortfolioObservabilityService(db_pool, redis_client)

    app.state.redis_client = redis_client
    app.state.db_pool = db_pool
    app.state.observability_service = service
    app.state._owns_valkey = owns_valkey
    app.state._owns_db = owns_db

    try:
        yield
    finally:
        if owns_valkey and redis_client is not None:
            await redis_client.aclose()
        if owns_db:
            await DBPoolManager.close_pools()


def create_app(
    *,
    observability_service: PortfolioObservabilityService | None = None,
    redis_client: Any | None = None,
    db_pool: Any | None = None,
) -> FastAPI:
    app = FastAPI(
        title="flipperAgent Portfolio Service",
        description="Internal portfolio analytics and observability API.",
        version="1.0.0",
        lifespan=lifespan,
    )
    if observability_service is not None:
        app.state.observability_service = observability_service
    if redis_client is not None:
        app.state.redis_client = redis_client
    if db_pool is not None:
        app.state.db_pool = db_pool
    app.include_router(router)
    return app


app = create_app()
