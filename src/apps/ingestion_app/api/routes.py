"""Typed HTTP routes for ingestion control and asset configuration."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.runtime.controller import (
    RuntimeControlConflictError,
    RuntimeController,
)
from apps.ingestion_app.runtime.supervisor import (
    DesiredRuntimeState,
    RuntimeState,
)
from apps.ingestion_app.services.config_reconciliation import (
    AssetAlreadyExistsError,
    AssetCandidateError,
    AssetConfigService,
    AssetNotFoundError,
)
from apps.ingestion_app.services.time_alignment import aligned_bucket_start
from apps.ingestion_app.settings import AssetSettings

from .dependencies import get_config_service, get_runtime_controller

router = APIRouter()


class RuntimeSnapshotResponse(BaseModel):
    desired_state: DesiredRuntimeState
    state: RuntimeState
    last_error: str | None
    enabled_asset_count: int


class HealthResponse(BaseModel):
    status: str
    runtime: RuntimeSnapshotResponse | None = None


class AssetsResponse(BaseModel):
    assets: list[AssetSettings]


class ProviderResponse(BaseModel):
    provider_id: str
    enabled: bool
    exchange_id: str | None


class ProvidersResponse(BaseModel):
    providers: list[ProviderResponse]


class AssetPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    updates: dict[str, Any]


class ManualRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str
    instrument_id: str
    since: datetime
    until: datetime

    @field_validator("asset", "instrument_id", mode="before")
    @classmethod
    def validate_text(cls, value: object, info: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        normalized = value.strip()
        return normalized.upper() if info.field_name == "asset" else normalized

    @model_validator(mode="after")
    def validate_bounds(self) -> ManualRecoveryRequest:
        for name, value in (("since", self.since), ("until", self.until)):
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError(f"{name} must be timezone-aware UTC")
        if self.until <= self.since:
            raise ValueError("until must be after since")
        return self


def _runtime_response(controller: RuntimeController) -> RuntimeSnapshotResponse:
    snapshot = controller.snapshot()
    return RuntimeSnapshotResponse(
        desired_state=snapshot.desired_state,
        state=snapshot.state,
        last_error=snapshot.last_error,
        enabled_asset_count=controller.enabled_asset_count,
    )


def _mutation_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AssetAlreadyExistsError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, AssetNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (AssetCandidateError, ValueError)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="asset mutation failed")


@router.get("/health/live", response_model=HealthResponse)
def health_live() -> HealthResponse:
    return HealthResponse(status="live")


@router.get("/health/ready", response_model=HealthResponse)
def health_ready(
    controller: RuntimeController = Depends(get_runtime_controller),  # noqa: B008
) -> HealthResponse:
    runtime = _runtime_response(controller)
    if not controller.is_started or runtime.state is RuntimeState.ERROR:
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "runtime": runtime.model_dump(mode="json")},
        )
    return HealthResponse(status="ready", runtime=runtime)


@router.get("/runtime", response_model=RuntimeSnapshotResponse)
def get_runtime(
    controller: RuntimeController = Depends(get_runtime_controller),  # noqa: B008
) -> RuntimeSnapshotResponse:
    return _runtime_response(controller)


@router.get("/assets", response_model=AssetsResponse)
def get_assets(
    service: AssetConfigService = Depends(get_config_service),  # noqa: B008
) -> AssetsResponse:
    return AssetsResponse(assets=list(service.list_assets()))


@router.get("/assets/{asset}", response_model=AssetSettings)
def get_asset(
    asset: str,
    service: AssetConfigService = Depends(get_config_service),  # noqa: B008
) -> AssetSettings:
    try:
        return service.get_asset(asset)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/assets", response_model=AssetSettings, status_code=201)
async def create_asset(
    asset: AssetSettings,
    service: AssetConfigService = Depends(get_config_service),  # noqa: B008
) -> AssetSettings:
    try:
        return await service.create_asset(asset)
    except Exception as exc:
        raise _mutation_http_error(exc) from exc


@router.patch("/assets/{asset}", response_model=AssetSettings)
async def patch_asset(
    asset: str,
    body: AssetPatchRequest,
    service: AssetConfigService = Depends(get_config_service),  # noqa: B008
) -> AssetSettings:
    try:
        return await service.patch_asset(asset, body.updates)
    except Exception as exc:
        raise _mutation_http_error(exc) from exc


@router.get("/providers", response_model=ProvidersResponse)
def get_providers(
    controller: RuntimeController = Depends(get_runtime_controller),  # noqa: B008
) -> ProvidersResponse:
    settings = controller.settings
    providers = [
        ProviderResponse(
            provider_id=provider_id,
            enabled=settings.providers[provider_id].enabled,
            exchange_id=settings.providers[provider_id].exchange_id,
        )
        for provider_id in sorted(settings.providers)
    ]
    return ProvidersResponse(providers=providers)


@router.post("/runtime/pause", response_model=RuntimeSnapshotResponse)
async def pause_runtime(
    controller: RuntimeController = Depends(get_runtime_controller),  # noqa: B008
) -> RuntimeSnapshotResponse:
    try:
        snapshot = await controller.pause()
    except RuntimeControlConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _runtime_response_from_snapshot(snapshot, controller)


@router.post("/runtime/resume", response_model=RuntimeSnapshotResponse)
async def resume_runtime(
    controller: RuntimeController = Depends(get_runtime_controller),  # noqa: B008
) -> RuntimeSnapshotResponse:
    try:
        snapshot = await controller.resume()
    except RuntimeControlConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _runtime_response_from_snapshot(snapshot, controller)


@router.post("/runtime/reconnect", response_model=RuntimeSnapshotResponse)
async def reconnect_runtime(
    controller: RuntimeController = Depends(get_runtime_controller),  # noqa: B008
) -> RuntimeSnapshotResponse:
    try:
        snapshot = await controller.reconnect()
    except RuntimeControlConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _runtime_response_from_snapshot(snapshot, controller)


def _runtime_response_from_snapshot(
    snapshot: Any,
    controller: RuntimeController,
) -> RuntimeSnapshotResponse:
    return RuntimeSnapshotResponse(
        desired_state=snapshot.desired_state,
        state=snapshot.state,
        last_error=snapshot.last_error,
        enabled_asset_count=controller.enabled_asset_count,
    )


def _validate_recovery_grid(
    *,
    since: datetime,
    until: datetime,
    controller: RuntimeController,
) -> None:
    settings = controller.settings
    base_duration = timedelta(
        seconds=settings.timeframes[settings.base_timeframe].duration_seconds
    )
    origin = settings.calendar.alignment_origin
    if aligned_bucket_start(since, base_duration, origin) != since:
        raise HTTPException(
            status_code=422,
            detail="since must align to the configured base timeframe grid",
        )
    if aligned_bucket_start(until, base_duration, origin) != until:
        raise HTTPException(
            status_code=422,
            detail="until must align to the configured base timeframe grid",
        )


@router.post("/runtime/recover", response_model=RuntimeSnapshotResponse)
async def recover_runtime(
    body: ManualRecoveryRequest,
    controller: RuntimeController = Depends(get_runtime_controller),  # noqa: B008
) -> RuntimeSnapshotResponse:
    settings = controller.settings
    asset = settings.assets.get(body.asset)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"unknown asset: {body.asset}")
    if not asset.enabled:
        raise HTTPException(status_code=409, detail="asset is disabled")
    instrument = asset.instruments.get(body.instrument_id)
    if instrument is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown instrument: {body.instrument_id}",
        )

    _validate_recovery_grid(
        since=body.since,
        until=body.until,
        controller=controller,
    )

    request = RecoveryRequest(
        lane=MarketLane(
            instrument.venue,
            body.instrument_id,
            settings.base_timeframe,
        ),
        since=body.since,
        until=body.until,
        reason="manual_api",
    )
    try:
        snapshot = await controller.recover(request)
    except RuntimeControlConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="manual recovery failed") from exc
    return _runtime_response_from_snapshot(snapshot, controller)


__all__ = ["router"]
