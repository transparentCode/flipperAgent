"""Liveness and readiness. No other routes in phase 1; no authentication."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.scraper_app.runtime.status import ReadinessReport

router = APIRouter()

ReadinessProvider = Callable[[], Awaitable[ReadinessReport]]


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready")
async def ready(request: Request) -> JSONResponse:
    provider: ReadinessProvider | None = getattr(request.app.state, "readiness", None)
    if provider is None:
        return JSONResponse({"status": "not_ready"}, status_code=503)
    report = await provider()
    return JSONResponse(report.payload(), status_code=report.http_status)


__all__ = ["ReadinessProvider", "router"]
