from __future__ import annotations

import json
from typing import Any

from apps.signal_app.models import SignalPair, SignalPairState, SignalRuntimeStatus
from libs.contracts.serialization import valkey_decode, valkey_encode


def runtime_status_key(asset: str, timeframe: str) -> str:
    return f"signal:status:{asset.upper()}:{timeframe}"


class SignalRuntimeStateStore:
    def __init__(self, redis_client: Any) -> None:
        self.redis_client = redis_client

    async def read(self, pair: SignalPair) -> SignalRuntimeStatus | None:
        if self.redis_client is None:
            return None
        raw = await self.redis_client.hgetall(runtime_status_key(pair.asset, pair.timeframe))
        if not raw:
            return None
        normalized = dict(raw)
        pair_value = normalized.get("pair")
        if isinstance(pair_value, bytes):
            pair_value = pair_value.decode("utf-8")
        if isinstance(pair_value, str):
            try:
                normalized["pair"] = json.loads(pair_value)
            except json.JSONDecodeError:
                pass
        return valkey_decode(normalized, SignalRuntimeStatus)

    async def write(self, status: SignalRuntimeStatus) -> SignalRuntimeStatus:
        if self.redis_client is None:
            return status
        await self.redis_client.hset(
            runtime_status_key(status.pair.asset, status.pair.timeframe),
            mapping=valkey_encode(status, inject_trace=False),
        )
        return status

    async def delete(self, pair: SignalPair) -> None:
        if self.redis_client is None:
            return
        await self.redis_client.delete(runtime_status_key(pair.asset, pair.timeframe))

    async def update(
        self,
        pair: SignalPair,
        *,
        state: SignalPairState | None = None,
        last_input_ts: float | None = None,
        last_feature_ts: float | None = None,
        lag_ms: int | None = None,
        last_error: str | None = None,
        replace_last_error: bool = False,
        detail: dict[str, Any] | None = None,
    ) -> SignalRuntimeStatus:
        current = await self.read(pair) or SignalRuntimeStatus(pair=pair)
        merged_detail = dict(current.detail)
        if detail:
            merged_detail.update(detail)
        updated = current.model_copy(
            update={
                "state": state if state is not None else current.state,
                "last_input_ts": (
                    last_input_ts if last_input_ts is not None else current.last_input_ts
                ),
                "last_feature_ts": (
                    last_feature_ts if last_feature_ts is not None else current.last_feature_ts
                ),
                "lag_ms": lag_ms if lag_ms is not None else current.lag_ms,
                "last_error": (
                    last_error if replace_last_error or last_error is not None else current.last_error
                ),
                "detail": merged_detail,
            }
        )
        return await self.write(updated)
