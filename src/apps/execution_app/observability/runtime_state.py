from __future__ import annotations

import json
from typing import Any

from apps.execution_app.state import ExecutionAsset, ExecutionRuntimeStatus
from libs.contracts.serialization import valkey_decode, valkey_encode


def runtime_status_key(asset: str) -> str:
    return f"execution:status:{asset.upper()}"


class ExecutionRuntimeStateStore:
    def __init__(self, redis_client: Any) -> None:
        self.redis_client = redis_client

    async def read(self, asset: ExecutionAsset) -> ExecutionRuntimeStatus | None:
        if self.redis_client is None:
            return None
        raw = await self.redis_client.hgetall(runtime_status_key(asset.asset))
        if not raw:
            return None
        normalized = dict(raw)
        asset_value = normalized.get("asset")
        if isinstance(asset_value, bytes):
            asset_value = asset_value.decode("utf-8")
        if isinstance(asset_value, str):
            try:
                normalized["asset"] = json.loads(asset_value)
            except json.JSONDecodeError:
                pass
        return valkey_decode(normalized, ExecutionRuntimeStatus)

    async def write(self, status: ExecutionRuntimeStatus) -> ExecutionRuntimeStatus:
        if self.redis_client is None:
            return status
        await self.redis_client.hset(
            runtime_status_key(status.asset.asset),
            mapping=valkey_encode(status, inject_trace=False),
        )
        return status

    async def delete(self, asset: ExecutionAsset) -> None:
        if self.redis_client is None:
            return
        await self.redis_client.delete(runtime_status_key(asset.asset))

    async def update(
        self,
        asset: ExecutionAsset,
        *,
        state: Any | None = None,
        mode: str | None = None,
        last_order_ts: float | None = None,
        last_fill_ts: float | None = None,
        last_failure_ts: float | None = None,
        last_error: str | None = None,
        replace_last_error: bool = False,
        increment_processed: int = 0,
        increment_failures: int = 0,
        detail: dict[str, Any] | None = None,
    ) -> ExecutionRuntimeStatus:
        current = await self.read(asset) or ExecutionRuntimeStatus(asset=asset)
        merged_detail = dict(current.detail)
        if detail:
            merged_detail.update(detail)
        updated = current.model_copy(
            update={
                "state": state if state is not None else current.state,
                "mode": mode if mode is not None else current.mode,
                "last_order_ts": last_order_ts if last_order_ts is not None else current.last_order_ts,
                "last_fill_ts": last_fill_ts if last_fill_ts is not None else current.last_fill_ts,
                "last_failure_ts": (
                    last_failure_ts if last_failure_ts is not None else current.last_failure_ts
                ),
                "processed_count": current.processed_count + increment_processed,
                "failure_count": current.failure_count + increment_failures,
                "last_error": (
                    last_error if replace_last_error or last_error is not None else current.last_error
                ),
                "detail": merged_detail,
            }
        )
        return await self.write(updated)
