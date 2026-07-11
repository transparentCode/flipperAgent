from __future__ import annotations

from typing import Any, Literal
import inspect

from pydantic import BaseModel, ConfigDict, field_validator

from libs.contracts.serialization import valkey_decode, valkey_encode

ASSET_STATUS_STREAM = "asset:status"
_ASSET_RUNTIME_STATUS_KEY_PREFIX = "ingestion:runtime_status"


class IngestionAssetRuntimeStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str
    timeframe: str
    runtime_state: Literal["COLD", "BACKFILLING", "WARMING", "LIVE", "ERROR"]
    downstream_ready: bool = False
    resume_backfill_required: bool = False
    reason: str | None = None
    provenance: str = "ingestion_app"
    updated_at: float
    last_ready_at: float | None = None
    last_live_at: float | None = None
    last_disconnect_at: float | None = None
    disconnects_in_window: int = 0
    source: str = "ingestion_app"

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return str(value).upper().strip()


def asset_runtime_status_key(symbol: str, timeframe: str) -> str:
    normalized_symbol = str(symbol).upper().strip()
    normalized_timeframe = str(timeframe).strip()
    return f"{_ASSET_RUNTIME_STATUS_KEY_PREFIX}:{normalized_symbol}:{normalized_timeframe}"


class AssetRuntimeStatusStore:
    def __init__(
        self,
        redis_client: Any,
        *,
        stream_maxlen: int = 5000,
        stream_approximate: bool = True,
    ) -> None:
        self.redis_client = redis_client
        self.stream_maxlen = stream_maxlen
        self.stream_approximate = stream_approximate

    async def write_status(self, status: IngestionAssetRuntimeStatus) -> str | None:
        await self.redis_client.hset(
            asset_runtime_status_key(status.symbol, status.timeframe),
            mapping=valkey_encode(status, inject_trace=False),
        )
        return await self.redis_client.xadd(
            ASSET_STATUS_STREAM,
            valkey_encode(status, inject_trace=False),
            maxlen=self.stream_maxlen,
            approximate=self.stream_approximate,
        )

    async def read_status(self, symbol: str, timeframe: str) -> IngestionAssetRuntimeStatus | None:
        hgetall = getattr(self.redis_client, "hgetall", None)
        if hgetall is None:
            return None
        raw = hgetall(asset_runtime_status_key(symbol, timeframe))
        if inspect.isawaitable(raw):
            raw = await raw
        elif not isinstance(raw, dict):
            return None
        if not raw:
            return None
        return valkey_decode(dict(raw), IngestionAssetRuntimeStatus)


__all__ = [
    "ASSET_STATUS_STREAM",
    "AssetRuntimeStatusStore",
    "IngestionAssetRuntimeStatus",
    "asset_runtime_status_key",
]
