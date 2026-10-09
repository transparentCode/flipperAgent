"""FastAPI application factory for the v2 collector."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.types import Lifespan

from apps.scraper_app.http_api.routes import ReadinessProvider, router
from apps.scraper_app.http_api.v2 import ApiDependencies, build_v2_router


def create_app(
    *,
    readiness: ReadinessProvider | None = None,
    lifespan: Lifespan[FastAPI] | None = None,
    api: ApiDependencies | None = None,
) -> FastAPI:
    app = FastAPI(
        title="flipperAgent Scraper Collector",
        version="2.0.0",
        lifespan=lifespan,
    )
    if readiness is not None:
        app.state.readiness = readiness
    app.include_router(router)
    if api is not None:
        app.include_router(build_v2_router(api))
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
