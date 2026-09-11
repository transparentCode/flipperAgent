from __future__ import annotations

from time import time
from typing import Protocol

from apps.alert_app.contracts import (
    AlertIncidentRecord,
    AlertIncidentState,
    AlertSummary,
    NormalizedAlertEvent,
    make_incident_id,
)


class _AlertRepositoryProtocol(Protocol):
    async def get_incident(self, incident_id: str) -> AlertIncidentRecord | None: ...

    async def get_by_dedupe_key(self, dedupe_key: str) -> AlertIncidentRecord | None: ...

    async def upsert_incident(
        self,
        incident: AlertIncidentRecord,
    ) -> AlertIncidentRecord: ...

    async def summary(self) -> AlertSummary: ...


class _AlertStoreProtocol(Protocol):
    async def incident_id_for_dedupe(self, dedupe_key: str) -> str | None: ...

    async def read(self, incident_id: str) -> AlertIncidentRecord | None: ...

    async def write(self, incident: AlertIncidentRecord) -> AlertIncidentRecord: ...

    async def write_hot_summary(self, summary: AlertSummary) -> None: ...


class AlertIncidentService:
    def __init__(
        self,
        repository: _AlertRepositoryProtocol,
        store: _AlertStoreProtocol,
        *,
        renotify_seconds: int = 1800,
    ) -> None:
        self.repository = repository
        self.store = store
        self.renotify_seconds = renotify_seconds

    async def record_event(
        self,
        event: NormalizedAlertEvent,
        *,
        route_names: list[str] | None = None,
    ) -> tuple[AlertIncidentRecord, bool]:
        if event.recovery_key:
            incident = await self._find_by_dedupe_key(event.recovery_key)
            if incident is not None:
                updated = incident.model_copy(
                    update={
                        "state": AlertIncidentState.RESOLVED,
                        "title": event.title,
                        "summary": event.summary,
                        "detail": dict(event.detail),
                        "last_seen_at": event.emitted_at,
                        "resolved_at": event.emitted_at,
                        "updated_at": event.emitted_at,
                    }
                )
                return await self._persist(updated), False

        existing = await self._find_by_dedupe_key(event.dedupe_key)
        if existing is None:
            incident = AlertIncidentRecord(
                incident_id=make_incident_id(event.dedupe_key),
                dedupe_key=event.dedupe_key,
                event_type=event.event_type,
                source_app=event.source_app,
                source_component=event.source_component,
                severity=event.severity,
                state=AlertIncidentState.OPEN,
                asset=event.asset,
                timeframe=event.timeframe,
                title=event.title,
                summary=event.summary,
                detail=dict(event.detail),
                route_names=list(route_names or []),
                first_seen_at=event.emitted_at,
                last_seen_at=event.emitted_at,
                last_notified_at=None,
                updated_at=event.emitted_at,
            )
            saved = await self._persist(incident)
            return saved, True

        merged_detail = dict(existing.detail)
        merged_detail.update(event.detail)
        now_ts = event.emitted_at or time()
        should_notify = existing.last_notified_at is None or (
            now_ts - existing.last_notified_at >= self.renotify_seconds
        )
        updated = existing.model_copy(
            update={
                "severity": event.severity,
                "state": AlertIncidentState.OPEN,
                "summary": event.summary,
                "detail": merged_detail,
                "occurrence_count": existing.occurrence_count + 1,
                "route_names": list(route_names or existing.route_names),
                "last_seen_at": now_ts,
                "updated_at": now_ts,
                "resolved_at": None,
            }
        )
        return await self._persist(updated), should_notify

    async def acknowledge(self, incident_id: str, *, acknowledged_at: float | None = None) -> AlertIncidentRecord | None:
        incident = await self._find_by_incident_id(incident_id)
        if incident is None:
            return None
        ts = acknowledged_at or time()
        updated = incident.model_copy(
            update={
                "state": AlertIncidentState.ACKED,
                "acknowledged_at": ts,
                "updated_at": ts,
            }
        )
        return await self._persist(updated)

    async def resolve(self, incident_id: str, *, resolved_at: float | None = None) -> AlertIncidentRecord | None:
        incident = await self._find_by_incident_id(incident_id)
        if incident is None:
            return None
        ts = resolved_at or time()
        updated = incident.model_copy(
            update={
                "state": AlertIncidentState.RESOLVED,
                "resolved_at": ts,
                "updated_at": ts,
            }
        )
        return await self._persist(updated)

    async def mark_notified(
        self,
        incident_id: str,
        *,
        notified_at: float | None = None,
    ) -> AlertIncidentRecord | None:
        incident = await self._find_by_incident_id(incident_id)
        if incident is None:
            return None
        ts = notified_at or time()
        updated = incident.model_copy(
            update={
                "last_notified_at": ts,
                "updated_at": ts,
            }
        )
        return await self._persist(updated)

    async def silence(self, incident_id: str, *, silenced_at: float | None = None) -> AlertIncidentRecord | None:
        incident = await self._find_by_incident_id(incident_id)
        if incident is None:
            return None
        ts = silenced_at or time()
        updated = incident.model_copy(
            update={
                "state": AlertIncidentState.SILENCED,
                "updated_at": ts,
            }
        )
        return await self._persist(updated)

    async def get_incident(self, incident_id: str) -> AlertIncidentRecord | None:
        return await self._find_by_incident_id(incident_id)

    async def incident_for_dedupe(self, dedupe_key: str) -> AlertIncidentRecord | None:
        return await self._find_by_dedupe_key(dedupe_key)

    async def _find_by_dedupe_key(self, dedupe_key: str) -> AlertIncidentRecord | None:
        incident_id = await self.store.incident_id_for_dedupe(dedupe_key)
        if incident_id:
            incident = await self.store.read(incident_id)
            if incident is not None:
                return incident
        return await self.repository.get_by_dedupe_key(dedupe_key)

    async def _find_by_incident_id(self, incident_id: str) -> AlertIncidentRecord | None:
        incident = await self.store.read(incident_id)
        if incident is not None:
            return incident
        return await self.repository.get_incident(incident_id)

    async def _persist(self, incident: AlertIncidentRecord) -> AlertIncidentRecord:
        saved = await self.repository.upsert_incident(incident)
        await self.store.write(saved)
        await self.store.write_hot_summary(await self.repository.summary())
        return saved
