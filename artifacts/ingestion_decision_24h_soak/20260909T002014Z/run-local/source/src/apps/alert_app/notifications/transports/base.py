from __future__ import annotations

from typing import Any, Protocol

from apps.alert_app.contracts import AlertIncidentRecord


class AlertTransport(Protocol):
    async def send(
        self,
        *,
        incident: AlertIncidentRecord,
        route_name: str,
        route_config: dict[str, Any],
    ) -> None: ...

