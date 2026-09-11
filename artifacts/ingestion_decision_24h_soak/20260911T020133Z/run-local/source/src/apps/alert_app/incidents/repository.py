from __future__ import annotations

import json
from typing import Any

from apps.alert_app.contracts import (
    AlertDeliveryRecord,
    AlertIncidentRecord,
    AlertIncidentState,
    AlertSeverity,
    AlertSilenceRule,
    AlertSourceApp,
    AlertSummary,
)


class AlertIncidentRepository:
    def __init__(self, db_pool: Any) -> None:
        self.db_pool = db_pool

    async def upsert_incident(self, incident: AlertIncidentRecord) -> AlertIncidentRecord:
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO alert_incidents (
                    incident_id,
                    dedupe_key,
                    event_type,
                    source_app,
                    source_component,
                    severity,
                    state,
                    asset,
                    timeframe,
                    title,
                    summary,
                    detail,
                    occurrence_count,
                    route_names,
                    first_seen_at,
                    last_seen_at,
                    last_notified_at,
                    acknowledged_at,
                    resolved_at,
                    updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11, $12::jsonb, $13, $14::jsonb, $15, $16, $17, $18, $19, $20
                )
                ON CONFLICT (incident_id) DO UPDATE SET
                    severity = EXCLUDED.severity,
                    state = EXCLUDED.state,
                    summary = EXCLUDED.summary,
                    detail = EXCLUDED.detail,
                    occurrence_count = EXCLUDED.occurrence_count,
                    route_names = EXCLUDED.route_names,
                    last_seen_at = EXCLUDED.last_seen_at,
                    last_notified_at = EXCLUDED.last_notified_at,
                    acknowledged_at = EXCLUDED.acknowledged_at,
                    resolved_at = EXCLUDED.resolved_at,
                    updated_at = EXCLUDED.updated_at
                """,
                incident.incident_id,
                incident.dedupe_key,
                incident.event_type.value,
                incident.source_app.value,
                incident.source_component,
                incident.severity.value,
                incident.state.value,
                incident.asset,
                incident.timeframe,
                incident.title,
                incident.summary,
                json.dumps(incident.detail),
                incident.occurrence_count,
                json.dumps(incident.route_names),
                incident.first_seen_at,
                incident.last_seen_at,
                incident.last_notified_at,
                incident.acknowledged_at,
                incident.resolved_at,
                incident.updated_at,
            )
        return incident

    async def get_incident(self, incident_id: str) -> AlertIncidentRecord | None:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM alert_incidents WHERE incident_id = $1",
                incident_id,
            )
        return _row_to_incident(row) if row else None

    async def get_by_dedupe_key(self, dedupe_key: str) -> AlertIncidentRecord | None:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM alert_incidents WHERE dedupe_key = $1",
                dedupe_key,
            )
        return _row_to_incident(row) if row else None

    async def list_incidents(
        self,
        *,
        state: str | None = None,
        severity: str | None = None,
        source_app: str | None = None,
        asset: str | None = None,
        timeframe: str | None = None,
        limit: int = 100,
    ) -> list[AlertIncidentRecord]:
        conditions: list[str] = []
        values: list[Any] = []
        if state:
            values.append(state)
            conditions.append(f"state = ${len(values)}")
        if severity:
            values.append(severity)
            conditions.append(f"severity = ${len(values)}")
        if source_app:
            values.append(source_app)
            conditions.append(f"source_app = ${len(values)}")
        if asset:
            values.append(asset.upper().strip())
            conditions.append(f"asset = ${len(values)}")
        if timeframe:
            values.append(timeframe.strip())
            conditions.append(f"timeframe = ${len(values)}")
        values.append(limit)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = (
            "SELECT * FROM alert_incidents "
            f"{where_clause} "
            f"ORDER BY updated_at DESC LIMIT ${len(values)}"
        )
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(query, *values)
        return [_row_to_incident(row) for row in rows]

    async def summary(self) -> AlertSummary:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT state, severity, source_app, COUNT(*) AS count
                FROM alert_incidents
                GROUP BY state, severity, source_app
                """
            )
            notification_failures = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM alert_notifications
                WHERE status = 'failed'
                """
            )

        summary = AlertSummary(notification_failures=int(notification_failures or 0))
        for row in rows:
            count = int(row["count"])
            state = str(row["state"])
            severity = str(row["severity"])
            source_app = str(row["source_app"])
            if state == AlertIncidentState.OPEN.value:
                summary.open_count += count
            elif state == AlertIncidentState.ACKED.value:
                summary.acked_count += count
            elif state == AlertIncidentState.SILENCED.value:
                summary.silenced_count += count
            elif state == AlertIncidentState.RESOLVED.value:
                summary.resolved_count += count
            summary.by_severity[severity] = summary.by_severity.get(severity, 0) + count
            summary.by_source_app[source_app] = (
                summary.by_source_app.get(source_app, 0) + count
            )
        return summary

    async def record_delivery(self, record: AlertDeliveryRecord) -> AlertDeliveryRecord:
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO alert_notifications (
                    delivery_id,
                    incident_id,
                    route_name,
                    transport,
                    status,
                    destination,
                    error,
                    attempted_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                record.delivery_id,
                record.incident_id,
                record.route_name,
                record.transport,
                record.status,
                record.destination,
                record.error,
                record.attempted_at,
            )
        return record

    async def recent_deliveries(self, *, limit: int = 100) -> list[AlertDeliveryRecord]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT delivery_id, incident_id, route_name, transport, status, destination, error, attempted_at
                FROM alert_notifications
                ORDER BY attempted_at DESC
                LIMIT $1
                """,
                limit,
            )
        return [
            AlertDeliveryRecord(
                delivery_id=str(row["delivery_id"]),
                incident_id=str(row["incident_id"]),
                route_name=str(row["route_name"]),
                transport=str(row["transport"]),
                status=str(row["status"]),
                destination=str(row["destination"]),
                error=row["error"],
                attempted_at=float(row["attempted_at"]),
            )
            for row in rows
        ]

    async def save_silence(self, silence: AlertSilenceRule) -> AlertSilenceRule:
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO alert_silences (
                    silence_id,
                    match,
                    reason,
                    created_by,
                    created_at,
                    expires_at
                ) VALUES ($1, $2::jsonb, $3, $4, $5, $6)
                ON CONFLICT (silence_id) DO UPDATE SET
                    match = EXCLUDED.match,
                    reason = EXCLUDED.reason,
                    created_by = EXCLUDED.created_by,
                    created_at = EXCLUDED.created_at,
                    expires_at = EXCLUDED.expires_at
                """,
                silence.silence_id,
                json.dumps(silence.match),
                silence.reason,
                silence.created_by,
                silence.created_at,
                silence.expires_at,
            )
        return silence

    async def list_silences(self) -> list[AlertSilenceRule]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM alert_silences ORDER BY created_at DESC"
            )
        return [
            AlertSilenceRule(
                silence_id=str(row["silence_id"]),
                match=dict(row["match"] or {}),
                reason=row["reason"],
                created_by=str(row["created_by"]),
                created_at=float(row["created_at"]),
                expires_at=float(row["expires_at"]) if row["expires_at"] is not None else None,
            )
            for row in rows
        ]

    async def delete_silence(self, silence_id: str) -> bool:
        async with self.db_pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM alert_silences WHERE silence_id = $1",
                silence_id,
            )
        return str(result).endswith("1")


def _row_to_incident(row: Any) -> AlertIncidentRecord:
    detail = _decode_json_mapping(row["detail"])
    route_names_list = _decode_json_list(row["route_names"])
    return AlertIncidentRecord(
        incident_id=str(row["incident_id"]),
        dedupe_key=str(row["dedupe_key"]),
        event_type=row["event_type"],
        source_app=AlertSourceApp(str(row["source_app"])),
        source_component=str(row["source_component"]),
        severity=AlertSeverity(str(row["severity"])),
        state=AlertIncidentState(str(row["state"])),
        asset=row["asset"],
        timeframe=row["timeframe"],
        title=str(row["title"]),
        summary=str(row["summary"]),
        detail=detail,
        occurrence_count=int(row["occurrence_count"]),
        route_names=route_names_list,
        first_seen_at=float(row["first_seen_at"]),
        last_seen_at=float(row["last_seen_at"]),
        last_notified_at=(
            float(row["last_notified_at"]) if row["last_notified_at"] is not None else None
        ),
        acknowledged_at=(
            float(row["acknowledged_at"]) if row["acknowledged_at"] is not None else None
        ),
        resolved_at=float(row["resolved_at"]) if row["resolved_at"] is not None else None,
        updated_at=float(row["updated_at"]),
    )


def _decode_json_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {}


def _decode_json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(decoded, list):
            return [str(item) for item in decoded]
        return []
    try:
        return [str(item) for item in value]
    except TypeError:
        return []
