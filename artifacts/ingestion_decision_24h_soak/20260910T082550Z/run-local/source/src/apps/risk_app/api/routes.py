from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from apps.risk_app.observability import RiskObservabilityService

router = APIRouter(prefix="/risk", tags=["risk"])


def _service(request: Request) -> RiskObservabilityService:
    return request.app.state.observability_service


@router.get("/health", summary="Risk observability health")
async def health(request: Request) -> dict[str, Any]:
    return await _service(request).health()


@router.get("/summary", summary="Compact risk account, order, and position summary")
async def summary(request: Request) -> dict[str, Any]:
    return await _service(request).summary()


@router.get("/latest", summary="Latest order request per asset")
async def latest_orders(
    request: Request,
    assets: list[str] | None = Query(default=None),
) -> dict[str, Any]:
    result = await _service(request).latest_orders(assets=assets)
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@router.get("/account", summary="Latest persisted risk account snapshot")
async def account_snapshot(request: Request) -> dict[str, Any]:
    result = await _service(request).account_snapshot()
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@router.get("/positions/open", summary="Current open risk positions")
async def open_positions(
    request: Request,
    asset: str | None = Query(default=None),
) -> dict[str, Any]:
    result = await _service(request).open_positions(asset=asset)
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@router.get("/status", summary="Per-asset risk runtime status derived from manifests, orders, and positions")
async def risk_status(request: Request) -> dict[str, Any]:
    result = await _service(request).status()
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return result
