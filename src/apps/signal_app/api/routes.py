from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from apps.signal_app.api.dependencies import get_signal_api_dependencies
from apps.signal_app.models import SignalFeatureSnapshotRequest, SignalPair, SignalRuntimeStatus

router = APIRouter(prefix="/signal", tags=["signal"])


@router.get("/pairs", response_model=list[SignalPair], summary="Effective signal pair catalog")
async def signal_pairs() -> list[SignalPair]:
    return get_signal_api_dependencies().catalog().list_pairs()


@router.get("/latest", summary="Latest feature vector per configured pair")
async def signal_latest() -> dict[str, Any]:
    service, valkey_client = await _open_observability_service()
    try:
        return await service.latest_features()
    finally:
        await valkey_client.aclose()


@router.get("/status", response_model=dict[str, SignalRuntimeStatus], summary="Signal pair runtime status")
async def signal_status() -> dict[str, SignalRuntimeStatus]:
    service, valkey_client = await _open_observability_service()
    try:
        return await service.status()
    finally:
        await valkey_client.aclose()


@router.post("/features/snapshot", summary="Compute an on-demand feature snapshot")
async def signal_feature_snapshot(body: SignalFeatureSnapshotRequest) -> dict[str, Any]:
    try:
        feature_vector = await get_signal_api_dependencies().snapshot_service().compute(
            asset=body.asset,
            timeframe=body.timeframe,
            lookback=body.lookback,
            bars=body.bars,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "status": "ok",
        "feature_vector": feature_vector.model_dump(mode="json"),
    }


async def _open_observability_service() -> tuple[Any, Any]:
    try:
        return await get_signal_api_dependencies().open_observability()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Valkey unavailable: {exc}") from exc
