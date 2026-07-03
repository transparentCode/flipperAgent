"""Internal FastAPI application for alert_app observability."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from apps.alert_app.api.routes import router
from apps.alert_app.incidents import AlertIncidentRepository, AlertIncidentService, AlertIncidentStore
from apps.alert_app.observability import AlertObservabilityService
from apps.alert_app.settings import AlertAppSettings, create_alert_config_manager
from apps.alert_app.storage import apply_alert_schema
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.db.pool_manager import DBPoolManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_mgr = create_alert_config_manager()
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
        db_pool = DBPoolManager.get_writer_pool()
        owns_db = True

    await apply_alert_schema(db_pool)
    settings = AlertAppSettings.from_config(config_mgr)
    store = AlertIncidentStore(
        redis_client,
        dedupe_ttl_seconds=settings.dedupe_ttl_seconds,
        open_state_ttl_seconds=settings.open_state_ttl_seconds,
        hot_summary_ttl_seconds=settings.hot_summary_ttl_seconds,
    )
    repository = AlertIncidentRepository(db_pool)
    incident_service = AlertIncidentService(
        repository,
        store,
        renotify_seconds=settings.renotify_seconds,
    )
    service = getattr(app.state, "observability_service", None)
    if service is None:
        service = AlertObservabilityService(
            db_pool,
            redis_client,
            repository=repository,
            store=store,
            incident_service=incident_service,
            config_mgr=config_mgr,
        )

    app.state.redis_client = redis_client
    app.state.db_pool = db_pool
    app.state.observability_service = service
    app.state._owns_valkey = owns_valkey
    app.state._owns_db = owns_db
    app.state._config_mgr = config_mgr

    try:
        yield
    finally:
        if owns_valkey and redis_client is not None:
            await redis_client.aclose()
        if owns_db:
            await DBPoolManager.close_pools()
        config_mgr.shutdown()


def create_app(
    *,
    observability_service: AlertObservabilityService | None = None,
    redis_client: Any | None = None,
    db_pool: Any | None = None,
) -> FastAPI:
    app = FastAPI(
        title="flipperAgent Alert Service",
        description="Internal alert incident and observability API.",
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
