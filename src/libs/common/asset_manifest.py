from __future__ import annotations

from enum import Enum
import hashlib
from time import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from libs.contracts.ingestion import IngestionCommandType
from libs.contracts.serialization import valkey_decode, valkey_encode

ASSET_LIFECYCLE_STREAM = "asset:lifecycle"


class AssetLifecycleEventType(str, Enum):
    ASSET_UPSERTED = "ASSET_UPSERTED"
    ASSET_UPDATED = "ASSET_UPDATED"
    ASSET_PAUSED = "ASSET_PAUSED"
    ASSET_STOPPED = "ASSET_STOPPED"
    ASSET_RESUMED = "ASSET_RESUMED"
    ASSET_REMOVE_REQUESTED = "ASSET_REMOVE_REQUESTED"


class AssetManifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str
    exchange: str = "binance"
    provider: str = "binance_native"
    base_timeframe: str = "1m"
    publish_timeframes: list[str] = Field(default_factory=list)
    timeframes: list[str] = Field(default_factory=list)
    historical_backfill_days: int = 2
    retention_days: int | None = None
    enabled: bool = True
    desired_state: str = "LIVE"
    asset_version: int = 1
    timeframe_version: int | None = None
    request_id: str | None = None
    updated_at: float
    source: str = "ingestion_app"

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return str(value).upper().strip()


class AssetTimeframeManifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str
    timeframe: str
    exchange: str = "binance"
    provider: str = "binance_native"
    base_timeframe: str = "1m"
    is_base_timeframe: bool = False
    historical_backfill_days: int = 2
    retention_days: int | None = None
    enabled: bool = True
    desired_state: str = "LIVE"
    asset_version: int = 1
    timeframe_version: int | None = None
    request_id: str | None = None
    updated_at: float
    source: str = "ingestion_app"

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return str(value).upper().strip()


class AssetLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: str
    event_type: AssetLifecycleEventType
    command_id: str | None = None
    command_type: str
    symbol: str
    exchange: str = "binance"
    provider: str = "binance_native"
    base_timeframe: str = "1m"
    publish_timeframes: list[str] = Field(default_factory=list)
    timeframes: list[str] = Field(default_factory=list)
    enabled: bool = True
    desired_state: str = "LIVE"
    request_id: str | None = None
    asset_version: int = 1
    timeframe_version: int | None = None
    requested_by: str = "api_app"
    reason: str | None = None
    emitted_at: float

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return str(value).upper().strip()


def asset_manifest_key(symbol: str) -> str:
    return f"asset:{str(symbol).upper().strip()}"


def asset_timeframe_manifest_key(symbol: str, timeframe: str) -> str:
    return f"asset:{str(symbol).upper().strip()}:tf:{str(timeframe).strip()}"


def lifecycle_event_type(command_type: IngestionCommandType) -> AssetLifecycleEventType:
    mapping = {
        IngestionCommandType.UPSERT_ASSET: AssetLifecycleEventType.ASSET_UPSERTED,
        IngestionCommandType.UPDATE_ASSET: AssetLifecycleEventType.ASSET_UPDATED,
        IngestionCommandType.PAUSE_ASSET: AssetLifecycleEventType.ASSET_PAUSED,
        IngestionCommandType.STOP_ASSET: AssetLifecycleEventType.ASSET_STOPPED,
        IngestionCommandType.RESUME_ASSET: AssetLifecycleEventType.ASSET_RESUMED,
        IngestionCommandType.REMOVE_ASSET: AssetLifecycleEventType.ASSET_REMOVE_REQUESTED,
    }
    return mapping[command_type]


def make_lifecycle_event_id(
    *,
    symbol: str,
    command_type: str,
    asset_version: int,
    request_id: str | None = None,
) -> str:
    raw = f"lifecycle|{str(symbol).upper().strip()}|{command_type}|{asset_version}|{request_id or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def manifest_runtime_timeframes(manifest: AssetManifest) -> list[str]:
    ordered: list[str] = []
    candidates = manifest.timeframes or [manifest.base_timeframe, *list(manifest.publish_timeframes)]
    for timeframe in candidates:
        normalized = str(timeframe).strip()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return ordered


def iter_live_manifest_timeframes(
    manifests: list[AssetManifest] | None,
) -> list[tuple[AssetManifest, str]]:
    entries: list[tuple[AssetManifest, str]] = []
    if not manifests:
        return entries
    for manifest in manifests:
        if not manifest.enabled or str(manifest.desired_state).upper() != "LIVE":
            continue
        for timeframe in manifest_runtime_timeframes(manifest):
            entries.append((manifest, timeframe))
    return entries


def live_manifest_pairs(manifests: list[AssetManifest] | None) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for manifest, timeframe in iter_live_manifest_timeframes(manifests):
        pair = (manifest.symbol, timeframe)
        if pair not in pairs:
            pairs.append(pair)
    return pairs


class AssetManifestStore:
    def __init__(
        self,
        redis_client: Any,
        *,
        lifecycle_stream_maxlen: int = 5000,
        lifecycle_stream_approximate: bool = True,
    ) -> None:
        self.redis_client = redis_client
        self.lifecycle_stream_maxlen = lifecycle_stream_maxlen
        self.lifecycle_stream_approximate = lifecycle_stream_approximate

    async def read_asset(self, symbol: str) -> AssetManifest | None:
        raw = await self.redis_client.hgetall(asset_manifest_key(symbol))
        if not raw:
            return None
        return valkey_decode(dict(raw), AssetManifest)

    async def read_timeframe(self, symbol: str, timeframe: str) -> AssetTimeframeManifest | None:
        raw = await self.redis_client.hgetall(asset_timeframe_manifest_key(symbol, timeframe))
        if not raw:
            return None
        return valkey_decode(dict(raw), AssetTimeframeManifest)

    async def list_assets(self) -> list[AssetManifest]:
        manifests: list[AssetManifest] = []
        for key in await self._iter_asset_manifest_keys():
            raw = await self.redis_client.hgetall(key)
            if raw:
                manifests.append(valkey_decode(dict(raw), AssetManifest))
        manifests.sort(key=lambda item: item.symbol)
        return manifests

    async def list_runtime_pairs(self) -> list[tuple[str, str]]:
        return live_manifest_pairs(await self.list_assets())

    async def sync_from_ingestion_asset(
        self,
        asset: Any,
        *,
        updated_at: float | None = None,
        request_id: str | None = None,
    ) -> tuple[AssetManifest, list[AssetTimeframeManifest]]:
        timestamp = updated_at if updated_at is not None else time()
        previous = await self.read_asset(asset.symbol)
        timeframes = self._all_timeframes(asset)
        previous_timeframes = set(previous.timeframes if previous is not None else [])
        current_timeframes = set(timeframes)

        manifest = AssetManifest(
            symbol=asset.symbol,
            exchange=asset.exchange,
            provider=asset.provider,
            base_timeframe=asset.base_timeframe,
            publish_timeframes=list(asset.publish_timeframes),
            timeframes=timeframes,
            historical_backfill_days=asset.historical_backfill_days,
            retention_days=asset.retention_days,
            enabled=asset.enabled,
            desired_state=self._enum_value(asset.desired_state),
            asset_version=int(getattr(asset, "asset_version", 1)),
            timeframe_version=int(
                getattr(asset, "timeframe_version", None) or getattr(asset, "asset_version", 1)
            ),
            request_id=request_id,
            updated_at=timestamp,
        )
        await self.redis_client.hset(
            asset_manifest_key(asset.symbol),
            mapping=valkey_encode(manifest, inject_trace=False),
        )

        timeframe_manifests: list[AssetTimeframeManifest] = []
        for timeframe in timeframes:
            timeframe_manifest = AssetTimeframeManifest(
                symbol=asset.symbol,
                timeframe=timeframe,
                exchange=asset.exchange,
                provider=asset.provider,
                base_timeframe=asset.base_timeframe,
                is_base_timeframe=timeframe == asset.base_timeframe,
                historical_backfill_days=asset.historical_backfill_days,
                retention_days=asset.retention_days,
                enabled=asset.enabled,
                desired_state=self._enum_value(asset.desired_state),
                asset_version=int(getattr(asset, "asset_version", 1)),
                timeframe_version=int(
                    getattr(asset, "timeframe_version", None) or getattr(asset, "asset_version", 1)
                ),
                request_id=request_id,
                updated_at=timestamp,
            )
            await self.redis_client.hset(
                asset_timeframe_manifest_key(asset.symbol, timeframe),
                mapping=valkey_encode(timeframe_manifest, inject_trace=False),
            )
            timeframe_manifests.append(timeframe_manifest)

        for stale_timeframe in sorted(previous_timeframes - current_timeframes):
            await self.redis_client.delete(asset_timeframe_manifest_key(asset.symbol, stale_timeframe))

        return manifest, timeframe_manifests

    async def publish_lifecycle_event(
        self,
        *,
        asset: Any,
        command_type: IngestionCommandType,
        requested_by: str,
        reason: str | None,
        emitted_at: float | None = None,
        event_id: str | None = None,
        command_id: str | None = None,
        request_id: str | None = None,
    ) -> str:
        timestamp = emitted_at if emitted_at is not None else time()
        asset_version = int(getattr(asset, "asset_version", 1))
        timeframe_version = int(getattr(asset, "timeframe_version", None) or asset_version)
        event = AssetLifecycleEvent(
            event_id=event_id
            or make_lifecycle_event_id(
                symbol=asset.symbol,
                command_type=command_type.value,
                asset_version=asset_version,
                request_id=request_id,
            ),
            event_type=lifecycle_event_type(command_type),
            command_id=command_id,
            command_type=command_type.value,
            symbol=asset.symbol,
            exchange=asset.exchange,
            provider=asset.provider,
            base_timeframe=asset.base_timeframe,
            publish_timeframes=list(asset.publish_timeframes),
            timeframes=self._all_timeframes(asset),
            enabled=asset.enabled,
            desired_state=self._enum_value(asset.desired_state),
            request_id=request_id,
            asset_version=asset_version,
            timeframe_version=timeframe_version,
            requested_by=requested_by,
            reason=reason,
            emitted_at=timestamp,
        )
        return await self.redis_client.xadd(
            ASSET_LIFECYCLE_STREAM,
            valkey_encode(event, inject_trace=False),
            maxlen=self.lifecycle_stream_maxlen,
            approximate=self.lifecycle_stream_approximate,
        )

    @staticmethod
    def _all_timeframes(asset: Any) -> list[str]:
        ordered: list[str] = []
        for timeframe in [asset.base_timeframe, *list(asset.publish_timeframes)]:
            normalized = str(timeframe).strip()
            if normalized and normalized not in ordered:
                ordered.append(normalized)
        return ordered

    @staticmethod
    def _enum_value(value: Any) -> str:
        return str(getattr(value, "value", value))

    async def _iter_asset_manifest_keys(self) -> list[str]:
        keys: list[str] = []
        scan_iter = getattr(self.redis_client, "scan_iter", None)
        if callable(scan_iter):
            async for raw_key in scan_iter(match="asset:*"):
                key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
                if await self._is_asset_manifest_key(key):
                    keys.append(key)
            return sorted(keys)
        for raw_key in await self.redis_client.keys("asset:*"):
            key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
            if await self._is_asset_manifest_key(key):
                keys.append(key)
        return sorted(keys)

    async def _is_asset_manifest_key(self, key: str) -> bool:
        if key == ASSET_LIFECYCLE_STREAM or ":tf:" in key:
            return False

        key_type_fn = getattr(self.redis_client, "type", None)
        if not callable(key_type_fn):
            return True

        raw_key_type = await key_type_fn(key)
        key_type = raw_key_type.decode("utf-8") if isinstance(raw_key_type, bytes) else str(raw_key_type)
        return key_type == "hash"
