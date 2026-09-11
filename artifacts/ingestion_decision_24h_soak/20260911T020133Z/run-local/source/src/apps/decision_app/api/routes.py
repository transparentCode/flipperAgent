"""Small cached-evidence-only decision service routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from apps.decision_app.api.dependencies import get_decision_service
from apps.decision_app.runtime.service import DecisionService, DecisionServiceSnapshot

router = APIRouter()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "items"):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def snapshot_payload(snapshot: DecisionServiceSnapshot) -> dict[str, Any]:
    return _jsonable(
        {
            "service_state": snapshot.service_state,
            "desired_state": snapshot.desired_state,
            "generation_id": snapshot.generation_id,
            "started_at": snapshot.started_at,
            "last_poll_at": snapshot.last_poll_at,
            "last_rebuild_at": snapshot.last_rebuild_at,
            "last_lifecycle_event_at": snapshot.last_lifecycle_event_at,
            "last_error": snapshot.last_error,
            "configured_asset_count": snapshot.configured_asset_count,
            "configured_lane_count": snapshot.configured_lane_count,
            "active_lane_count": snapshot.active_lane_count,
            "lane_status_counts": snapshot.lane_status_counts,
            "blocked_stream_count": snapshot.blocked_stream_count,
            "lifecycle_cursor": snapshot.lifecycle_cursor,
            "lanes": snapshot.lanes,
            "inputs": snapshot.inputs,
            "last_lifecycle_evidence": snapshot.last_lifecycle_evidence,
        }
    )


def _service_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready")
def health_ready(
    service: DecisionService = Depends(get_decision_service),  # noqa: B008
) -> dict[str, Any]:
    snapshot = service.snapshot()
    payload = snapshot_payload(snapshot)
    if not snapshot.ready:
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "runtime": payload},
        )
    return {
        "status": "ready" if snapshot.service_state == "RUNNING" else "degraded",
        **payload,
    }


@router.get("/runtime")
def runtime(
    service: DecisionService = Depends(get_decision_service),  # noqa: B008
) -> dict[str, Any]:
    return snapshot_payload(service.snapshot())


@router.get("/runtime/lanes")
def runtime_lanes(
    service: DecisionService = Depends(get_decision_service),  # noqa: B008
) -> dict[str, Any]:
    snapshot = service.snapshot()
    return {
        "service_state": snapshot.service_state,
        "generation_id": snapshot.generation_id,
        "active_lane_count": snapshot.active_lane_count,
        "lane_status_counts": _jsonable(snapshot.lane_status_counts),
        "lanes": _jsonable(snapshot.lanes),
    }


@router.get("/runtime/inputs")
def runtime_inputs(
    service: DecisionService = Depends(get_decision_service),  # noqa: B008
) -> dict[str, Any]:
    snapshot = service.snapshot()
    return {
        "service_state": snapshot.service_state,
        "generation_id": snapshot.generation_id,
        "lifecycle_cursor": snapshot.lifecycle_cursor,
        "blocked_stream_count": snapshot.blocked_stream_count,
        "inputs": _jsonable(snapshot.inputs),
    }


@router.post("/runtime/pause")
async def pause_runtime(
    service: DecisionService = Depends(get_decision_service),  # noqa: B008
) -> dict[str, Any]:
    try:
        return snapshot_payload(await service.pause())
    except RuntimeError as exc:
        raise _service_error(exc) from exc


@router.post("/runtime/resume")
async def resume_runtime(
    service: DecisionService = Depends(get_decision_service),  # noqa: B008
) -> dict[str, Any]:
    try:
        return snapshot_payload(await service.resume())
    except RuntimeError as exc:
        raise _service_error(exc) from exc


@router.post("/runtime/reconnect")
async def reconnect_runtime(
    service: DecisionService = Depends(get_decision_service),  # noqa: B008
) -> dict[str, Any]:
    try:
        return snapshot_payload(await service.reconnect())
    except RuntimeError as exc:
        raise _service_error(exc) from exc


__all__ = ["router", "snapshot_payload"]
