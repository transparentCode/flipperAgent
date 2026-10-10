"""FastAPI application factory for the v2 collector."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.types import Lifespan

from apps.scraper_app.http_api.auth import make_auth_dependency
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
        # The interactive docs are open pages; the schema is served under /v2.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    if readiness is not None:
        app.state.readiness = readiness
    app.include_router(router)
    if api is not None:
        app.include_router(build_v2_router(api))

        @app.exception_handler(OverflowError)
        async def _overflow(_request: Request, _exc: OverflowError) -> JSONResponse:
            body = {"code": "invalid_request", "message": "value out of range"}
            return JSONResponse({"detail": body}, status_code=422)

        openapi_dependency = make_auth_dependency(api.tokens)

        @app.get(
            "/v2/openapi.json",
            include_in_schema=False,
            dependencies=[Depends(openapi_dependency)],
        )
        async def openapi_schema() -> JSONResponse:
            return JSONResponse(app.openapi())

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
