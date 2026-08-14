"""Testable FastAPI application factory for D9C."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.types import Lifespan

from apps.decision_app.api.routes import router
from apps.decision_app.service import DecisionService


def create_app(
    *,
    decision_service: DecisionService | None = None,
    lifespan: Lifespan[FastAPI] | None = None,
) -> FastAPI:
    app = FastAPI(
        title="flipperAgent Decision Service",
        version="1.0.0",
        lifespan=lifespan,
    )
    if decision_service is not None:
        app.state.decision_service = decision_service
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
