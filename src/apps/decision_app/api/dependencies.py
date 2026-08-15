"""Dependency accessors for the injected decision control plane."""

from __future__ import annotations

from typing import cast

from fastapi import HTTPException, Request

from apps.decision_app.runtime.service import DecisionService


def get_decision_service(request: Request) -> DecisionService:
    service = getattr(request.app.state, "decision_service", None)
    if service is None or not callable(getattr(service, "snapshot", None)):
        raise HTTPException(status_code=503, detail="decision service is not ready")
    return cast(DecisionService, service)


__all__ = ["get_decision_service"]
