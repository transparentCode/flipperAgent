"""Testable FastAPI application factory for ingestion control."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.types import Lifespan

from apps.ingestion_app.runtime.controller import RuntimeController
from apps.ingestion_app.services.config_reconciliation import AssetConfigService

from .routes import router


def create_app(
    *,
    runtime_controller: RuntimeController | None = None,
    config_service: AssetConfigService | None = None,
    lifespan: Lifespan[FastAPI] | None = None,
) -> FastAPI:
    app = FastAPI(
        title="flipperAgent Ingestion Control Plane",
        version="1.0.0",
        lifespan=lifespan,
    )
    if runtime_controller is not None:
        app.state.runtime_controller = runtime_controller
    if config_service is not None:
        app.state.config_service = config_service
    app.include_router(router)
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls=r"/health/(live|ready)$",
        )
    except ImportError:
        pass
    return app


__all__ = ["create_app"]
