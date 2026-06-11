from __future__ import annotations

import uuid
from time import time
from typing import Any

from apps.ingestion_app.constants import INGESTION_EVENTS_STREAM
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import IngestionEventType, IngestionRuntimeEvent, valkey_encode

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)


async def publish_ingestion_runtime_event(
    valkey_client: Any | None,
    *,
    event_type: IngestionEventType,
    symbol: str,
    timeframe: str | None = None,
    severity: str = "warning",
    detail: dict[str, Any] | None = None,
) -> str | None:
    if valkey_client is None:
        return None

    event = IngestionRuntimeEvent(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        symbol=symbol,
        timeframe=timeframe,
        severity=severity,
        detail=detail or {},
        emitted_at=time(),
    )

    try:
        return await valkey_client.xadd(
            INGESTION_EVENTS_STREAM,
            valkey_encode(event),
            maxlen=10_000,
            approximate=True,
        )
    except Exception as exc:
        logger.warning(
            "Failed to publish ingestion runtime event for %s (%s): %s",
            symbol,
            event_type.value,
            exc,
            exc_info=True,
        )
        return None
