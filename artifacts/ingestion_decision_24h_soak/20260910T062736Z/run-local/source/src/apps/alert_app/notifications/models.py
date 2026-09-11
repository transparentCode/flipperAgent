from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AlertNotificationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    incident_id: str
    route_name: str
    transport: str
    destination: str
    title: str
    summary: str
    severity: str
    queued_at: float

