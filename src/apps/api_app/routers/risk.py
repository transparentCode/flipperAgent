"""Risk observability router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from apps.risk_app.observability import RiskObservabilityService
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.db.pool_manager import DBPoolManager

router = APIRouter(prefix="/risk", tags=["risk"])

config_manager = ConfigManager()


async def _call_service(method_name: str, **kwargs: Any) -> dict[str, Any]:
    valkey_client = await create_valkey_client(config_manager)
    try:
        service = RiskObservabilityService(
            DBPoolManager.get_reader_pool(),
            valkey_client,
            config_mgr=config_manager,
        )
        result = await getattr(service, method_name)(**kwargs)
    finally:
        await valkey_client.aclose()
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@router.get("/health", summary="Risk observability health")
async def risk_health() -> dict[str, Any]:
    return await _call_service("health")


@router.get("/summary", summary="Compact risk account, order, and position summary")
async def risk_summary() -> dict[str, Any]:
    return await _call_service("summary")


@router.get("/latest", summary="Latest order request per asset")
async def risk_latest(assets: list[str] | None = Query(default=None)) -> dict[str, Any]:
    return await _call_service("latest_orders", assets=assets)


@router.get("/account", summary="Latest persisted risk account snapshot")
async def risk_account() -> dict[str, Any]:
    return await _call_service("account_snapshot")


@router.get("/positions/open", summary="Current open risk positions")
async def risk_open_positions(asset: str | None = Query(default=None)) -> dict[str, Any]:
    return await _call_service("open_positions", asset=asset)


@router.get("/status", summary="Per-asset risk status derived from manifests, orders, and positions")
async def risk_status() -> dict[str, Any]:
    return await _call_service("status")
