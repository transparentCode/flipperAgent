"""Dependency accessors for the injected ingestion control plane."""

from __future__ import annotations

from typing import cast

from fastapi import HTTPException, Request

from apps.ingestion_app.runtime.controller import RuntimeController
from apps.ingestion_app.services.config_reconciliation import AssetConfigService


def get_runtime_controller(request: Request) -> RuntimeController:
    controller = getattr(request.app.state, "runtime_controller", None)
    if controller is None or not callable(getattr(controller, "snapshot", None)):
        raise HTTPException(status_code=503, detail="runtime controller is not ready")
    return cast(RuntimeController, controller)


def get_config_service(request: Request) -> AssetConfigService:
    service = getattr(request.app.state, "config_service", None)
    if service is None or not callable(getattr(service, "list_assets", None)):
        raise HTTPException(status_code=503, detail="asset config service is not ready")
    return cast(AssetConfigService, service)


__all__ = ["get_config_service", "get_runtime_controller"]
