from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from apps.alert_app.contracts import AlertIncidentRecord


class WebhookAlertTransport:
    async def send(
        self,
        *,
        incident: AlertIncidentRecord,
        route_name: str,
        route_config: dict[str, Any],
    ) -> None:
        destination = str(route_config.get("destination", "")).strip()
        if not destination:
            raise ValueError(f"Webhook route {route_name} missing destination")
        timeout_seconds = float(route_config.get("timeout_seconds", 10))
        max_attempts = max(1, int(route_config.get("max_attempts", 3)))
        backoff_seconds = max(0.0, float(route_config.get("backoff_seconds", 1)))
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        headers = _build_headers(route_config)
        payload = {
            "incident_id": incident.incident_id,
            "route_name": route_name,
            "severity": incident.severity.value,
            "state": incident.state.value,
            "asset": incident.asset,
            "timeframe": incident.timeframe,
            "title": incident.title,
            "summary": incident.summary,
            "detail": incident.detail,
            "updated_at": incident.updated_at,
        }
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                    async with session.post(destination, json=payload) as response:
                        if response.status >= 400:
                            body = await response.text()
                            raise RuntimeError(
                                f"Webhook transport failed for {route_name}: "
                                f"status={response.status} body={body[:200]}"
                            )
                        return
            except Exception as exc:
                last_error = exc
                if attempt >= max_attempts:
                    break
                await asyncio.sleep(backoff_seconds * attempt)
        assert last_error is not None
        raise last_error


def _build_headers(route_config: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    configured_headers = route_config.get("headers", {}) or {}
    for key, value in configured_headers.items():
        normalized_key = str(key).strip()
        normalized_value = str(value).strip()
        if normalized_key and normalized_value:
            headers[normalized_key] = normalized_value
    authorization_header = str(route_config.get("authorization_header", "") or "").strip()
    if authorization_header:
        headers["Authorization"] = authorization_header
    return headers
