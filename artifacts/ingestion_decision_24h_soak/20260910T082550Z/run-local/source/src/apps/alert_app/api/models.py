from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AlertSilenceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    match: dict[str, str] = Field(default_factory=dict)
    reason: str | None = None
    created_by: str = "operator"
    expires_at: float | None = None


class AlertIncidentActionResponse(BaseModel):
    status: str
    incident: dict[str, Any]

