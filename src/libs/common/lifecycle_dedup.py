from __future__ import annotations

from typing import Any


async def mark_lifecycle_event_processed(
    redis_client: Any,
    *,
    consumer_namespace: str,
    event_id: str,
    ttl_seconds: int = 86_400,
) -> bool:
    key = f"{consumer_namespace}:lifecycle:event:{event_id}"
    result = await redis_client.set(key, "1", ex=ttl_seconds, nx=True)
    return bool(result)
