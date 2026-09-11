"""Execution observability router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.execution_app.observability.status import ExecutionObservabilityService
from apps.execution_app.state import ExecutionAsset, ExecutionRuntimeStatus
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.discovery import discover_pairs

router = APIRouter(prefix="/execution", tags=["execution"])

config_manager = ConfigManager()


@router.get("/fills", summary="Latest fill report per asset")
async def execution_fills() -> dict[str, Any]:
    """Return the most recently published ``ExecutionReport`` for every
    configured asset, plus a staleness indicator.

    Reads the tail of ``fills:{asset}`` streams via XREVRANGE LIMIT 1.
    Creates a short-lived Valkey connection per request — suitable for
    low-frequency operational polling (not a hot path).

    Response shape per asset::

        {
          "BTCUSDT": {
            "stream": "fills:BTCUSDT",
            "message_id": "1234567890123-0",
            "timestamp": 1717000000.0,
            "lag_ms": 800,
            "status": "ok",
            "order_id": "a1b2c3d4e5f6",
            "side": "buy",
            "requested_size": 0.012345,
            "filled_size": 0.012345,
            "requested_price": 67450.5,
            "average_fill_price": 67453.9,
            "fill_status": "filled",
            "slippage_bps": 0.50,
            "stop_loss_price": 65800.0,
            "take_profit_price": 69200.0,
            "idempotency_key": "abc123...",
            "error_message": null
          }
        }

    ``status`` values:

    - ``ok`` — fill found, data valid
    - ``no_data`` — stream exists but no fill has been published yet
    - ``error`` — unexpected Valkey error
    """
    service, valkey_client = await _open_observability_service()
    try:
        result = await service.latest_fills()
    finally:
        await valkey_client.aclose()

    return result


@router.get("/status", response_model=dict[str, ExecutionRuntimeStatus], summary="Per-asset execution runtime status")
async def execution_status() -> dict[str, ExecutionRuntimeStatus]:
    service, valkey_client = await _open_observability_service()
    try:
        return await service.status()
    finally:
        await valkey_client.aclose()


@router.get("/failures", summary="Latest execution failure per asset")
async def execution_failures() -> dict[str, Any]:
    service, valkey_client = await _open_observability_service()
    try:
        return await service.latest_failures()
    finally:
        await valkey_client.aclose()


@router.get("/summary", summary="Execution runtime summary")
async def execution_summary() -> dict[str, Any]:
    service, valkey_client = await _open_observability_service()
    try:
        return await service.summary()
    finally:
        await valkey_client.aclose()


async def _open_observability_service() -> tuple[ExecutionObservabilityService, Any]:
    assets = _discover_execution_assets()
    valkey_client = await create_valkey_client(config_manager)
    return ExecutionObservabilityService(valkey_client, assets), valkey_client


def _discover_execution_assets() -> list[ExecutionAsset]:
    pairs = discover_pairs(config_manager)
    seen: set[str] = set()
    assets: list[ExecutionAsset] = []
    for asset, _ in pairs:
        normalized = asset.upper().strip()
        if normalized not in seen:
            seen.add(normalized)
            assets.append(ExecutionAsset(asset=normalized))
    return assets
