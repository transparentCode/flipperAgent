from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from apps.alert_app.api.models import AlertSilenceCreateRequest
from apps.alert_app.observability import AlertObservabilityService

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _service(request: Request) -> AlertObservabilityService:
    return request.app.state.observability_service


@router.get("/health", summary="alert_app health")
async def health(request: Request) -> dict[str, Any]:
    return await _service(request).health()


@router.get("/summary", summary="alert incident summary")
async def summary(request: Request) -> dict[str, Any]:
    return await _service(request).summary()


@router.get("/incidents", summary="List alert incidents")
async def incidents(
    request: Request,
    state: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    source_app: str | None = Query(default=None),
    asset: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    result = await _service(request).incidents(
        state=state,
        severity=severity,
        source_app=source_app,
        asset=asset,
        timeframe=timeframe,
        limit=limit,
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@router.get("/incidents/{incident_id}", summary="Get alert incident detail")
async def incident_detail(
    request: Request,
    incident_id: str,
) -> dict[str, Any]:
    result = await _service(request).incident_detail(incident_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return result


@router.get("/routes", summary="Resolved alert routes from config")
async def routes(request: Request) -> dict[str, Any]:
    return await _service(request).routes()


@router.get("/silences", summary="Configured silence rules")
async def silences(request: Request) -> dict[str, Any]:
    return await _service(request).silences()


@router.get("/notifications", summary="Recent alert notification delivery attempts")
async def notifications(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    return await _service(request).notifications(limit=limit)


@router.post("/incidents/{incident_id}/ack", summary="Acknowledge an alert incident")
async def acknowledge_incident(
    request: Request,
    incident_id: str,
) -> dict[str, Any]:
    result = await _service(request).acknowledge_incident(incident_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return result


@router.post("/incidents/{incident_id}/resolve", summary="Resolve an alert incident")
async def resolve_incident(
    request: Request,
    incident_id: str,
) -> dict[str, Any]:
    result = await _service(request).resolve_incident(incident_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return result


@router.post("/silences", summary="Create an alert silence rule")
async def create_silence(
    request: Request,
    body: AlertSilenceCreateRequest,
) -> dict[str, Any]:
    return await _service(request).create_silence(
        match=body.match,
        reason=body.reason,
        created_by=body.created_by,
        expires_at=body.expires_at,
    )


@router.delete("/silences/{silence_id}", summary="Delete an alert silence rule")
async def delete_silence(
    request: Request,
    silence_id: str,
) -> dict[str, Any]:
    result = await _service(request).delete_silence(silence_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Silence {silence_id} not found")
    return result
