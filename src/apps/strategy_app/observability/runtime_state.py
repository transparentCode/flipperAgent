from __future__ import annotations

import json
from typing import Any

from apps.strategy_app.state import StrategyPair, StrategyRuntimeStatus
from libs.contracts.serialization import valkey_decode, valkey_encode


def runtime_status_key(
    asset: str,
    timeframe: str,
    trigger_timeframe: str | None = None,
) -> str:
    normalized_asset = asset.upper()
    normalized_timeframe = timeframe.strip()
    normalized_trigger = str(trigger_timeframe or "").strip()
    if normalized_trigger and normalized_trigger != normalized_timeframe:
        return f"strategy:status:{normalized_asset}:{normalized_timeframe}@{normalized_trigger}"
    return f"strategy:status:{normalized_asset}:{normalized_timeframe}"


class StrategyRuntimeStateStore:
    def __init__(self, redis_client: Any) -> None:
        self.redis_client = redis_client

    async def read(self, pair: StrategyPair) -> StrategyRuntimeStatus | None:
        if self.redis_client is None:
            return None
        raw = await self.redis_client.hgetall(
            runtime_status_key(pair.asset, pair.timeframe, pair.trigger_timeframe)
        )
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
        return valkey_decode(normalized, StrategyRuntimeStatus)

    async def write(self, status: StrategyRuntimeStatus) -> StrategyRuntimeStatus:
        if self.redis_client is None:
            return status
        await self.redis_client.hset(
            runtime_status_key(
                status.pair.asset,
                status.pair.timeframe,
                status.pair.trigger_timeframe,
            ),
            mapping=valkey_encode(status, inject_trace=False),
        )
        return status

    async def delete(self, pair: StrategyPair) -> None:
        if self.redis_client is None:
            return
        await self.redis_client.delete(
            runtime_status_key(pair.asset, pair.timeframe, pair.trigger_timeframe)
        )

    async def update(
        self,
        pair: StrategyPair,
        *,
        state: Any | None = None,
        last_feature_ts: float | None = None,
        last_signal_ts: float | None = None,
        lag_ms: int | None = None,
        last_error: str | None = None,
        replace_last_error: bool = False,
        detail: dict[str, Any] | None = None,
    ) -> StrategyRuntimeStatus:
        current = await self.read(pair) or StrategyRuntimeStatus(pair=pair)
        merged_detail = dict(current.detail)
        if detail:
            merged_detail.update(detail)
        updated = current.model_copy(
            update={
                "state": state if state is not None else current.state,
                "last_feature_ts": (
                    last_feature_ts if last_feature_ts is not None else current.last_feature_ts
                ),
                "last_signal_ts": (
                    last_signal_ts if last_signal_ts is not None else current.last_signal_ts
                ),
                "lag_ms": lag_ms if lag_ms is not None else current.lag_ms,
                "last_error": (
                    last_error if replace_last_error or last_error is not None else current.last_error
                ),
                "detail": merged_detail,
            }
        )
        return await self.write(updated)
