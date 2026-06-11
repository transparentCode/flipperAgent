"""Ingestion observability router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.ingestion_app.asset_registry import IngestionAssetCatalog, IngestionControlService
from apps.ingestion_app.coordination import IngestionCoordinator
from apps.ingestion_app.models.asset_registry import (
    IngestionAssetActionRequest,
    IngestionAssetDesiredState,
    IngestionAssetPatchRequest,
    IngestionAssetRecord,
    IngestionAssetUpsertRequest,
    IngestionControlResult,
)
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.db.pool_manager import DBPoolManager
from libs.contracts.schemas import IngestionCommandType

router = APIRouter(prefix="/ingestion", tags=["ingestion"])

config_manager = ConfigManager()


@router.get("/assets", response_model=list[IngestionAssetRecord], summary="Effective ingestion asset catalog")
async def ingestion_assets() -> list[IngestionAssetRecord]:
    """Return registry-backed assets, falling back to config defaults when the
    registry is empty or not yet bootstrapped.
    """
    catalog = IngestionAssetCatalog(config_manager=config_manager)
    return await catalog.list_effective_assets()


@router.get("/assets/{symbol}", response_model=IngestionAssetRecord, summary="Single effective ingestion asset")
async def ingestion_asset(symbol: str) -> IngestionAssetRecord:
    catalog = IngestionAssetCatalog(config_manager=config_manager)
    asset = await catalog.get_effective_asset(symbol)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Ingestion asset '{symbol.upper()}' not found.")
    return asset


@router.post("/assets", response_model=IngestionControlResult, summary="Create or replace an ingestion asset")
async def upsert_ingestion_asset(body: IngestionAssetUpsertRequest) -> IngestionControlResult:
    valkey_client = await _safe_create_valkey_client()
    try:
        service = IngestionControlService(
            pool=DBPoolManager.get_writer_pool(),
            valkey_client=valkey_client,
        )
        return await service.upsert_asset(body, command_type=IngestionCommandType.UPSERT_ASSET)
    finally:
        if valkey_client is not None:
            await valkey_client.aclose()


@router.patch("/assets/{symbol}", response_model=IngestionControlResult, summary="Patch an existing ingestion asset")
async def patch_ingestion_asset(
    symbol: str,
    body: IngestionAssetPatchRequest,
) -> IngestionControlResult:
    existing = await _require_effective_asset(symbol)
    valkey_client = await _safe_create_valkey_client()
    try:
        service = IngestionControlService(
            pool=DBPoolManager.get_writer_pool(),
            valkey_client=valkey_client,
        )
        return await service.patch_asset(existing, body)
    finally:
        if valkey_client is not None:
            await valkey_client.aclose()


@router.post("/assets/{symbol}/pause", response_model=IngestionControlResult, summary="Pause an ingestion asset")
async def pause_ingestion_asset(
    symbol: str,
    body: IngestionAssetActionRequest,
) -> IngestionControlResult:
    return await _apply_asset_action(
        symbol=symbol,
        body=body,
        desired_state=IngestionAssetDesiredState.PAUSED,
        enabled=True,
        action=IngestionCommandType.PAUSE_ASSET,
    )


@router.post("/assets/{symbol}/resume", response_model=IngestionControlResult, summary="Resume an ingestion asset")
async def resume_ingestion_asset(
    symbol: str,
    body: IngestionAssetActionRequest,
) -> IngestionControlResult:
    return await _apply_asset_action(
        symbol=symbol,
        body=body,
        desired_state=IngestionAssetDesiredState.LIVE,
        enabled=True,
        action=IngestionCommandType.RESUME_ASSET,
    )


@router.delete("/assets/{symbol}", response_model=IngestionControlResult, summary="Mark an ingestion asset for removal")
async def remove_ingestion_asset(
    symbol: str,
    body: IngestionAssetActionRequest,
) -> IngestionControlResult:
    return await _apply_asset_action(
        symbol=symbol,
        body=body,
        desired_state=IngestionAssetDesiredState.REMOVING,
        enabled=False,
        action=IngestionCommandType.REMOVE_ASSET,
    )


@router.get("/status", summary="Per-asset ingestion observability snapshot")
async def ingestion_status() -> dict:
    """Return state, last_live_ts, last_disconnect_ts, and disconnects_in_window
    for every effective asset/timeframe pair.

    Creates a short-lived Valkey connection per request — suitable for low-frequency
    operational polling (not a hot path).
    """
    assets = await IngestionAssetCatalog(config_manager=config_manager).list_effective_assets()

    valkey_client = await create_valkey_client(config_manager)
    try:
        coordinator = IngestionCoordinator(valkey_client, config_manager)
        snapshots = {}
        for asset in assets:
            snapshots[f"{asset.symbol}:{asset.base_timeframe}"] = await coordinator.get_observability_snapshot(
                asset.symbol, asset.base_timeframe
            )
    finally:
        await valkey_client.aclose()

    return snapshots


async def _require_effective_asset(symbol: str) -> IngestionAssetRecord:
    asset = await IngestionAssetCatalog(config_manager=config_manager).get_effective_asset(symbol)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Ingestion asset '{symbol.upper()}' not found.")
    return asset


async def _apply_asset_action(
    *,
    symbol: str,
    body: IngestionAssetActionRequest,
    desired_state: IngestionAssetDesiredState,
    enabled: bool,
    action: IngestionCommandType,
) -> IngestionControlResult:
    existing = await _require_effective_asset(symbol)
    valkey_client = await _safe_create_valkey_client()
    try:
        service = IngestionControlService(
            pool=DBPoolManager.get_writer_pool(),
            valkey_client=valkey_client,
        )
        return await service.apply_action(
            existing,
            desired_state=desired_state,
            enabled=enabled,
            action=action,
            body=body,
        )
    finally:
        if valkey_client is not None:
            await valkey_client.aclose()


async def _safe_create_valkey_client():
    try:
        return await create_valkey_client(config_manager)
    except Exception:
        return None
