from __future__ import annotations

import json
from typing import Any

from apps.alert_app.contracts import AlertIncidentRecord, AlertSummary
from apps.alert_app.incidents.keys import (
    dedupe_key_key,
    hot_summary_key,
    incident_key,
    open_incidents_key,
)
from libs.contracts.serialization import valkey_decode, valkey_encode


class AlertIncidentStore:
    def __init__(
        self,
        redis_client: Any,
        *,
        dedupe_ttl_seconds: int = 900,
        open_state_ttl_seconds: int = 7 * 24 * 60 * 60,
        hot_summary_ttl_seconds: int = 120,
    ) -> None:
        self.redis_client = redis_client
        self.dedupe_ttl_seconds = dedupe_ttl_seconds
        self.open_state_ttl_seconds = open_state_ttl_seconds
        self.hot_summary_ttl_seconds = hot_summary_ttl_seconds

    async def read(self, incident_id: str) -> AlertIncidentRecord | None:
        if self.redis_client is None:
            return None
        raw = await self.redis_client.hgetall(incident_key(incident_id))
        if not raw:
            return None
        normalized = dict(raw)
        detail_value = normalized.get("detail")
        route_names_value = normalized.get("route_names")
        if isinstance(detail_value, str):
            try:
                normalized["detail"] = json.loads(detail_value)
            except json.JSONDecodeError:
                pass
        if isinstance(route_names_value, str):
            try:
                normalized["route_names"] = json.loads(route_names_value)
            except json.JSONDecodeError:
                pass
        return valkey_decode(normalized, AlertIncidentRecord)

    async def write(self, incident: AlertIncidentRecord) -> AlertIncidentRecord:
        if self.redis_client is None:
            return incident
        key = incident_key(incident.incident_id)
        await self.redis_client.hset(
            key,
            mapping=valkey_encode(incident, inject_trace=False),
        )
        await self.redis_client.expire(key, self.open_state_ttl_seconds)
        await self.redis_client.set(
            dedupe_key_key(incident.dedupe_key),
            incident.incident_id,
            ex=self.dedupe_ttl_seconds,
        )
        if incident.state == incident.state.OPEN:
            await self.redis_client.sadd(open_incidents_key(), incident.incident_id)
        else:
            await self.redis_client.srem(open_incidents_key(), incident.incident_id)
        return incident

    async def delete(self, incident_id: str, *, dedupe_key: str | None = None) -> None:
        if self.redis_client is None:
            return
        await self.redis_client.delete(incident_key(incident_id))
        await self.redis_client.srem(open_incidents_key(), incident_id)
        if dedupe_key:
            await self.redis_client.delete(dedupe_key_key(dedupe_key))

    async def incident_id_for_dedupe(self, dedupe_key: str) -> str | None:
        if self.redis_client is None:
            return None
        value = await self.redis_client.get(dedupe_key_key(dedupe_key))
        if not value:
            return None
        return str(value)

    async def list_open_incident_ids(self) -> list[str]:
        if self.redis_client is None:
            return []
        values = await self.redis_client.smembers(open_incidents_key())
        return sorted(str(value) for value in values)

    async def write_hot_summary(self, summary: AlertSummary) -> None:
        if self.redis_client is None:
            return
        await self.redis_client.set(
            hot_summary_key(),
            summary.model_dump_json(),
            ex=self.hot_summary_ttl_seconds,
        )

    async def read_hot_summary(self) -> AlertSummary | None:
        if self.redis_client is None:
            return None
        raw = await self.redis_client.get(hot_summary_key())
        if not raw:
            return None
        return AlertSummary.model_validate_json(raw)

