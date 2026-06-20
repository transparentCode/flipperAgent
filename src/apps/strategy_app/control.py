from __future__ import annotations

import json
import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from apps.strategy_app.state import StrategyPair
from libs.contracts.serialization import valkey_decode, valkey_encode


class StrategyDesiredState(str, Enum):
    LIVE = "LIVE"
    PAUSED = "PAUSED"


class StrategyControlRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pair: StrategyPair
    desired_state: StrategyDesiredState = StrategyDesiredState.LIVE
    updated_at: float
    reason: str | None = None

    @field_validator("updated_at", mode="before")
    @classmethod
    def normalize_updated_at(cls, value: object) -> float:
        return float(value)


def strategy_control_key(
    asset: str,
    timeframe: str,
    trigger_timeframe: str | None = None,
) -> str:
    normalized_asset = asset.upper()
    normalized_timeframe = timeframe.strip()
    normalized_trigger = str(trigger_timeframe or "").strip()
    if normalized_trigger and normalized_trigger != normalized_timeframe:
        return f"strategy:control:{normalized_asset}:{normalized_timeframe}@{normalized_trigger}"
    return f"strategy:control:{normalized_asset}:{normalized_timeframe}"


class StrategyControlStore:
    def __init__(self, redis_client: Any) -> None:
        self.redis_client = redis_client

    async def read(self, pair: StrategyPair) -> StrategyControlRecord | None:
        if self.redis_client is None:
            return None
        raw = await self.redis_client.hgetall(
            strategy_control_key(pair.asset, pair.timeframe, pair.trigger_timeframe)
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
        return valkey_decode(normalized, StrategyControlRecord)

    async def write(self, record: StrategyControlRecord) -> StrategyControlRecord:
        if self.redis_client is None:
            return record
        await self.redis_client.hset(
            strategy_control_key(
                record.pair.asset,
                record.pair.timeframe,
                record.pair.trigger_timeframe,
            ),
            mapping=valkey_encode(record, inject_trace=False),
        )
        return record

    async def delete(self, pair: StrategyPair) -> None:
        if self.redis_client is None:
            return
        await self.redis_client.delete(
            strategy_control_key(pair.asset, pair.timeframe, pair.trigger_timeframe)
        )

    async def set_desired_state(
        self,
        pair: StrategyPair,
        desired_state: StrategyDesiredState,
        *,
        reason: str | None = None,
    ) -> StrategyControlRecord:
        return await self.write(
            StrategyControlRecord(
                pair=pair,
                desired_state=desired_state,
                updated_at=time.time() * 1000,
                reason=reason,
            )
        )

    async def desired_state(self, pair: StrategyPair) -> StrategyDesiredState:
        current = await self.read(pair)
        if current is None:
            return StrategyDesiredState.LIVE
        return current.desired_state

    async def is_paused(self, pair: StrategyPair) -> bool:
        return await self.desired_state(pair) == StrategyDesiredState.PAUSED
