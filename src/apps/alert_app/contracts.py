from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertIncidentState(str, Enum):
    OPEN = "open"
    ACKED = "acked"
    SILENCED = "silenced"
    RESOLVED = "resolved"


class AlertSourceApp(str, Enum):
    INGESTION = "ingestion"
    SIGNAL = "signal_app"
    STRATEGY = "strategy_app"
    RISK = "risk_app"
    EXECUTION = "execution_app"
    SCRAPER = "scraper_app"
    PORTFOLIO = "portfolio_app"
    ALERT = "alert_app"
    SYSTEM = "system"


class AlertEventType(str, Enum):
    LIFECYCLE_EVENT = "lifecycle_event"
    INGESTION_RUNTIME_FAILURE = "ingestion_runtime_failure"
    INGESTION_GAP_FILL_FAILURE = "ingestion_gap_fill_failure"
    INGESTION_PURGE_FAILURE = "ingestion_purge_failure"
    EXECUTION_FAILURE = "execution_failure"
    SIGNAL_FRESHNESS_BREACH = "signal_freshness_breach"
    STRATEGY_FRESHNESS_BREACH = "strategy_freshness_breach"
    SCRAPER_FAILURE = "scraper_failure"
    TRANSPORT_FAILURE = "transport_failure"
    SYSTEM_HEALTH_BREACH = "system_health_breach"
    RECOVERY = "recovery"


class AlertRouteConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    enabled: bool = True
    transport: str = "webhook"
    destination: str
    severity_min: AlertSeverity = AlertSeverity.WARNING
    burst_limit: int = 20
    burst_window_seconds: int = 300
    renotify_seconds: int = 1800


class AlertSilenceRule(BaseModel):
    model_config = ConfigDict(extra="ignore")

    silence_id: str
    match: dict[str, str] = Field(default_factory=dict)
    reason: str | None = None
    created_by: str = "system"
    created_at: float
    expires_at: float | None = None


class NormalizedAlertEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: str
    event_type: AlertEventType
    source_app: AlertSourceApp
    source_component: str
    severity: AlertSeverity = AlertSeverity.WARNING
    asset: str | None = None
    timeframe: str | None = None
    title: str
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)
    dedupe_key: str
    recovery_key: str | None = None
    emitted_at: float

    @field_validator("asset", mode="before")
    @classmethod
    def normalize_asset(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).upper().strip()
        return normalized or None

    @field_validator("timeframe", mode="before")
    @classmethod
    def normalize_timeframe(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class AlertIncidentRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    incident_id: str
    dedupe_key: str
    event_type: AlertEventType
    source_app: AlertSourceApp
    source_component: str
    severity: AlertSeverity = AlertSeverity.WARNING
    state: AlertIncidentState = AlertIncidentState.OPEN
    asset: str | None = None
    timeframe: str | None = None
    title: str
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)
    occurrence_count: int = 1
    route_names: list[str] = Field(default_factory=list)
    first_seen_at: float
    last_seen_at: float
    last_notified_at: float | None = None
    acknowledged_at: float | None = None
    resolved_at: float | None = None
    updated_at: float

    @field_validator("asset", mode="before")
    @classmethod
    def normalize_asset(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).upper().strip()
        return normalized or None

    @field_validator("timeframe", mode="before")
    @classmethod
    def normalize_timeframe(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class AlertDeliveryRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    delivery_id: str
    incident_id: str
    route_name: str
    transport: str
    status: str
    destination: str
    error: str | None = None
    attempted_at: float


class AlertSummary(BaseModel):
    open_count: int = 0
    acked_count: int = 0
    silenced_count: int = 0
    resolved_count: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_source_app: dict[str, int] = Field(default_factory=dict)
    notification_failures: int = 0


def make_incident_id(dedupe_key: str) -> str:
    return hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()[:24]
