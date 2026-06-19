"""Ingestion observability router."""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException

from apps.api_app.clients import ScraperServiceClient, ScraperServiceClientError
from apps.ingestion_app.constants import INGESTION_EVENTS_STREAM
from apps.ingestion_app.control_plane import IngestionAssetCatalog, IngestionControlService
from apps.ingestion_app.coordination import IngestionCoordinator
from apps.ingestion_app.models.asset_registry import (
    IngestionAssetActionRequest,
    IngestionAssetBatchActionRequest,
    IngestionAssetBatchUpsertRequest,
    IngestionAssetDesiredState,
    IngestionAssetPatchRequest,
    IngestionAssetRecord,
    IngestionAssetUpsertRequest,
    IngestionControlResult,
)
from apps.scraper_app.core.models import ScrapeJobRecord, ScrapeRequest, ScrapeResult
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import IngestionCommandType

router = APIRouter(prefix="/ingestion", tags=["ingestion"])

config_manager = ConfigManager()
logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)


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


@router.post("/assets/batch", response_model=list[IngestionControlResult], summary="Create or replace ingestion assets in batch")
async def batch_upsert_ingestion_assets(body: IngestionAssetBatchUpsertRequest) -> list[IngestionControlResult]:
    if not body.assets:
        return []

    valkey_client = await _safe_create_valkey_client()
    try:
        service = IngestionControlService(
            pool=DBPoolManager.get_writer_pool(),
            valkey_client=valkey_client,
        )
        results: list[IngestionControlResult] = []
        for asset in body.assets:
            results.append(await service.upsert_asset(asset, command_type=IngestionCommandType.UPSERT_ASSET))
        return results
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


@router.post("/assets/{symbol}/stop", response_model=IngestionControlResult, summary="Stop an ingestion asset")
async def stop_ingestion_asset(
    symbol: str,
    body: IngestionAssetActionRequest,
) -> IngestionControlResult:
    return await _apply_asset_action(
        symbol=symbol,
        body=body,
        desired_state=IngestionAssetDesiredState.STOPPED,
        enabled=False,
        action=IngestionCommandType.STOP_ASSET,
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


@router.post("/assets/batch/action", response_model=list[IngestionControlResult], summary="Apply the same lifecycle action to multiple ingestion assets")
async def batch_apply_ingestion_asset_action(
    body: IngestionAssetBatchActionRequest,
) -> list[IngestionControlResult]:
    if not body.symbols:
        return []

    desired_state, enabled, action = _batch_action_contract(body.desired_state)
    valkey_client = await _safe_create_valkey_client()
    try:
        service = IngestionControlService(
            pool=DBPoolManager.get_writer_pool(),
            valkey_client=valkey_client,
        )
        results: list[IngestionControlResult] = []
        action_body = IngestionAssetActionRequest(
            request_id=body.request_id,
            reason=body.reason,
            requested_by=body.requested_by,
        )
        for symbol in body.symbols:
            existing = await _require_effective_asset(symbol)
            results.append(
                await service.apply_action(
                    existing,
                    desired_state=desired_state,
                    enabled=enabled,
                    action=action,
                    body=action_body,
                )
            )
        return results
    finally:
        if valkey_client is not None:
            await valkey_client.aclose()


@router.get("/status", summary="Per-asset ingestion observability snapshot")
async def ingestion_status() -> dict:
    """Return per-asset ingestion runtime state and timing metadata
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


@router.get("/events", summary="Recent ingestion control/runtime events")
async def ingestion_events(
    limit: int = 50,
    symbol: str | None = None,
    event_type: str | None = None,
) -> dict[str, Any]:
    """Return recent decoded ingestion events from the shared Valkey event stream.

    Supports lightweight filtering on ``symbol`` and ``event_type`` after reading
    the most recent stream entries.
    """
    limit = max(1, min(limit, 200))
    valkey_client = await create_valkey_client(config_manager)
    try:
        messages = await valkey_client.xrevrange(INGESTION_EVENTS_STREAM, count=limit * 4)
        events = [
            _decode_ingestion_event(message_id, payload)
            for message_id, payload in messages
        ]
        if symbol is not None:
            normalized_symbol = symbol.upper()
            events = [entry for entry in events if str(entry.get("symbol", "")).upper() == normalized_symbol]
        if event_type is not None:
            normalized_event_type = event_type.upper()
            events = [
                entry for entry in events if str(entry.get("event_type", "")).upper() == normalized_event_type
            ]
        events = events[:limit]
        return {"stream": INGESTION_EVENTS_STREAM, "count": len(events), "events": events}
    finally:
        await valkey_client.aclose()


@router.get("/ops-summary", summary="Compact latest ingestion failure and job outcome summary")
async def ingestion_ops_summary(scan_limit: int = 200) -> dict[str, Any]:
    """Summarize the latest notable ingestion events for operators.

    The summary intentionally stays lightweight until a dedicated alerting app
    exists: latest failure, latest runtime retry exhaustion, latest gap-fill
    failure, latest purge result, and most recent accepted command.
    """
    scan_limit = max(10, min(scan_limit, 500))
    valkey_client = await create_valkey_client(config_manager)
    try:
        messages = await valkey_client.xrevrange(INGESTION_EVENTS_STREAM, count=scan_limit)
        events = [
            _decode_ingestion_event(message_id, payload)
            for message_id, payload in messages
        ]
    finally:
        await valkey_client.aclose()

    return {
        "stream": INGESTION_EVENTS_STREAM,
        "scanned_count": len(events),
        "last_command_accepted": _first_matching_event(
            events,
            lambda entry: entry.get("event_type") == "COMMAND_ACCEPTED",
        ),
        "last_failure": _first_matching_event(
            events,
            lambda entry: entry.get("severity") in {"error", "critical"}
            or entry.get("event_type") in {"GAP_FILL_FAILED", "ASSET_PURGE_FAILED", "RUNTIME_RETRY_EXHAUSTED"},
        ),
        "last_runtime_retry_exhausted": _first_matching_event(
            events,
            lambda entry: entry.get("event_type") == "RUNTIME_RETRY_EXHAUSTED",
        ),
        "last_gap_fill_failure": _first_matching_event(
            events,
            lambda entry: entry.get("event_type") == "GAP_FILL_FAILED",
        ),
        "last_gap_fill_result": _first_matching_event(
            events,
            lambda entry: entry.get("event_type") in {"GAP_FILL_COMPLETED", "GAP_FILL_FAILED"},
        ),
        "last_purge_result": _first_matching_event(
            events,
            lambda entry: entry.get("event_type") in {"ASSET_PURGE_COMPLETED", "ASSET_PURGE_FAILED"},
        ),
    }


@router.post(
    "/scraper/fetch",
    response_model=ScrapeResult,
    summary="Request on-demand scraper-backed provider data synchronously",
)
async def ingestion_scraper_fetch(body: ScrapeRequest) -> ScrapeResult:
    """Bridge on-demand provider pulls through scraper_app without coupling them
    into the live ingestion runtime loop.
    """
    try:
        return await _scraper_client().fetch_sync(body)
    except ScraperServiceClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/scraper/jobs",
    response_model=ScrapeJobRecord,
    summary="Queue an async on-demand scraper request",
)
async def ingestion_scraper_create_job(body: ScrapeRequest) -> ScrapeJobRecord:
    try:
        return await _scraper_client().create_job(body)
    except ScraperServiceClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get(
    "/scraper/jobs/{job_id}",
    response_model=ScrapeJobRecord,
    summary="Get async on-demand scraper job status",
)
async def ingestion_scraper_get_job(
    job_id: str,
    include_result: bool = True,
) -> ScrapeJobRecord:
    try:
        return await _scraper_client().get_job(job_id, include_result=include_result)
    except ScraperServiceClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


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


def _batch_action_contract(
    desired_state: IngestionAssetDesiredState,
) -> tuple[IngestionAssetDesiredState, bool, IngestionCommandType]:
    mapping = {
        IngestionAssetDesiredState.PAUSED: (
            IngestionAssetDesiredState.PAUSED,
            True,
            IngestionCommandType.PAUSE_ASSET,
        ),
        IngestionAssetDesiredState.STOPPED: (
            IngestionAssetDesiredState.STOPPED,
            False,
            IngestionCommandType.STOP_ASSET,
        ),
        IngestionAssetDesiredState.LIVE: (
            IngestionAssetDesiredState.LIVE,
            True,
            IngestionCommandType.RESUME_ASSET,
        ),
        IngestionAssetDesiredState.REMOVING: (
            IngestionAssetDesiredState.REMOVING,
            False,
            IngestionCommandType.REMOVE_ASSET,
        ),
    }
    return mapping[desired_state]


def _decode_ingestion_event(message_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    decoded: dict[str, Any] = {
        "stream_id": message_id.decode() if isinstance(message_id, bytes) else message_id,
    }
    for raw_key, raw_value in payload.items():
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        value = raw_value.decode() if isinstance(raw_value, bytes) else raw_value
        decoded[key] = _maybe_parse_json(value)

    emitted_at = decoded.get("emitted_at")
    lag_ms = None
    try:
        lag_ms = max(0, int(time.time() * 1000) - int(float(emitted_at) * 1000))
    except (TypeError, ValueError):
        lag_ms = None

    decoded["lag_ms"] = lag_ms
    decoded["kind"] = "control" if "command_id" in decoded else "runtime"
    return decoded


def _maybe_parse_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _first_matching_event(events: list[dict[str, Any]], predicate) -> dict[str, Any] | None:
    for entry in events:
        if predicate(entry):
            return entry
    return None


def _scraper_client() -> ScraperServiceClient:
    return ScraperServiceClient(config_manager=config_manager)


async def _safe_create_valkey_client():
    try:
        return await create_valkey_client(config_manager)
    except Exception as exc:
        logger.warning(f"Ingestion control proceeding without Valkey publisher: {exc}", exc_info=True)
        return None
