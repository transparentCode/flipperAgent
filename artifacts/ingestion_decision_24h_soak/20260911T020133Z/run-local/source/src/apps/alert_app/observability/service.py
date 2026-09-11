from __future__ import annotations

from time import time
from typing import Any
from uuid import uuid4

from apps.alert_app.contracts import AlertSilenceRule, AlertSummary
from apps.alert_app.incidents import AlertIncidentRepository, AlertIncidentStore
from apps.alert_app.incidents.service import AlertIncidentService
from apps.alert_app.settings import route_configs_from_config
from libs.common.config import ConfigManager


class AlertObservabilityService:
    def __init__(
        self,
        db_pool: Any,
        redis_client: Any | None = None,
        *,
        repository: AlertIncidentRepository | None = None,
        store: AlertIncidentStore | None = None,
        incident_service: AlertIncidentService | None = None,
        config_mgr: ConfigManager | None = None,
    ) -> None:
        self.db_pool = db_pool
        self.redis_client = redis_client
        self.repository = repository or AlertIncidentRepository(db_pool)
        self.config_mgr = config_mgr or ConfigManager()
        self.store = store or AlertIncidentStore(redis_client)
        self.incident_service = incident_service or AlertIncidentService(
            self.repository,
            self.store,
        )

    async def health(self) -> dict[str, Any]:
        db_available = False
        valkey_available = False
        db_error: str | None = None
        valkey_error: str | None = None

        try:
            async with self.db_pool.acquire() as conn:
                await conn.fetchrow("SELECT 1")
            db_available = True
        except Exception as exc:
            db_error = str(exc)

        if self.redis_client is not None:
            try:
                valkey_available = bool(await self.redis_client.ping())
            except Exception as exc:
                valkey_error = str(exc)

        result: dict[str, Any] = {
            "status": "ok" if db_available else "degraded",
            "db_available": db_available,
            "valkey_available": valkey_available,
        }
        if db_error is not None:
            result["db_error"] = db_error
        if valkey_error is not None:
            result["valkey_error"] = valkey_error
        return result

    async def summary(self) -> dict[str, Any]:
        hot_summary = await self.store.read_hot_summary()
        summary = hot_summary or await self.repository.summary()
        if hot_summary is None:
            await self.store.write_hot_summary(summary)
        return summary.model_dump(mode="json")

    async def incidents(
        self,
        *,
        state: str | None = None,
        severity: str | None = None,
        source_app: str | None = None,
        asset: str | None = None,
        timeframe: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        incidents = await self.repository.list_incidents(
            state=state,
            severity=severity,
            source_app=source_app,
            asset=asset,
            timeframe=timeframe,
            limit=limit,
        )
        return {
            "status": "ok" if incidents else "no_data",
            "count": len(incidents),
            "items": [incident.model_dump(mode="json") for incident in incidents],
        }

    async def incident_detail(self, incident_id: str) -> dict[str, Any]:
        incident = await self.incident_service.get_incident(incident_id)
        if incident is None:
            return {"status": "not_found", "incident_id": incident_id}
        return {
            "status": "ok",
            "incident": incident.model_dump(mode="json"),
        }

    async def routes(self) -> dict[str, Any]:
        routes = route_configs_from_config(self.config_mgr)
        return {
            "status": "ok",
            "count": len(routes),
            "items": {
                name: _redact_route_config(config)
                for name, config in routes.items()
            },
        }

    async def silences(self) -> dict[str, Any]:
        rules = await self.repository.list_silences()
        return {
            "status": "ok" if rules else "no_data",
            "count": len(rules),
            "items": [rule.model_dump(mode="json") for rule in rules],
        }

    async def acknowledge_incident(self, incident_id: str) -> dict[str, Any]:
        incident = await self.incident_service.acknowledge(incident_id)
        if incident is None:
            return {"status": "not_found", "incident_id": incident_id}
        return {
            "status": "ok",
            "incident": incident.model_dump(mode="json"),
        }

    async def resolve_incident(self, incident_id: str) -> dict[str, Any]:
        incident = await self.incident_service.resolve(incident_id)
        if incident is None:
            return {"status": "not_found", "incident_id": incident_id}
        return {
            "status": "ok",
            "incident": incident.model_dump(mode="json"),
        }

    async def create_silence(
        self,
        *,
        match: dict[str, str],
        reason: str | None = None,
        created_by: str = "operator",
        expires_at: float | None = None,
    ) -> dict[str, Any]:
        silence = AlertSilenceRule(
            silence_id=str(uuid4()),
            match=match,
            reason=reason,
            created_by=created_by,
            created_at=time(),
            expires_at=expires_at,
        )
        await self.repository.save_silence(silence)
        return {
            "status": "ok",
            "silence": silence.model_dump(mode="json"),
        }

    async def delete_silence(self, silence_id: str) -> dict[str, Any]:
        deleted = await self.repository.delete_silence(silence_id)
        if not deleted:
            return {"status": "not_found", "silence_id": silence_id}
        return {
            "status": "ok",
            "silence_id": silence_id,
        }

    async def notifications(self, *, limit: int = 100) -> dict[str, Any]:
        deliveries = await self.repository.recent_deliveries(limit=limit)
        counts: dict[str, int] = {}
        for delivery in deliveries:
            counts[delivery.status] = counts.get(delivery.status, 0) + 1
        return {
            "status": "ok" if deliveries else "no_data",
            "count": len(deliveries),
            "counts": counts,
            "items": [delivery.model_dump(mode="json") for delivery in deliveries],
        }


def _redact_route_config(config: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(config)
    for field in ("bot_token", "authorization_header"):
        value = redacted.get(field)
        if value not in (None, ""):
            redacted[field] = "[redacted]"
    return redacted
