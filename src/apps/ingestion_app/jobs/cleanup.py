from __future__ import annotations

from typing import Any

from apps.ingestion_app.constants import INGESTION_LAST_CLOSED_PUBLISHED_PREFIX
from apps.ingestion_app.control_plane.repository import IngestionAssetRegistryRepository
from apps.ingestion_app.coordination import IngestionCoordinator
from apps.ingestion_app.events import publish_ingestion_runtime_event
from apps.ingestion_app.models.asset_registry import IngestionAssetDesiredState
from apps.ingestion_app.storage.janitor import IngestionStorageJanitor
from libs.common.asset_status import asset_runtime_status_key
from libs.common.asset_manifest import asset_manifest_key, asset_timeframe_manifest_key
from libs.common.db.pool_manager import DBPoolManager
from libs.common.exceptions import DataIngestionError
from libs.common.stream_keys import feature_stream_key, price_update_stream_key
from libs.contracts.schemas import IngestionEventType

from apps.ingestion_app.jobs.shared import config_manager


async def purge_removed_asset(
    ctx: dict[str, Any],
    symbol: str,
    base_timeframe: str | None = None,
) -> None:
    timeframe = base_timeframe or config_manager.get("ingestion.timeframes.base_gap_fill", "1m")
    valkey_client = ctx.get("valkey_client")
    pool = DBPoolManager.get_writer_pool()
    janitor = IngestionStorageJanitor(pool)
    registry = IngestionAssetRegistryRepository(pool)

    try:
        asset = await registry.get_asset(symbol)
        if asset is not None and asset.desired_state != IngestionAssetDesiredState.REMOVING:
            return
        deleted_rows = await janitor.purge_asset_data(symbol)
        registry_deleted = await janitor.finalize_asset_removal(symbol)
        await _clear_ingestion_observability_keys_and_streams(
            valkey_client,
            symbol,
            timeframe,
            publish_timeframes=asset.publish_timeframes if asset is not None else [],
        )
        await publish_ingestion_runtime_event(
            valkey_client,
            event_type=IngestionEventType.ASSET_PURGE_COMPLETED,
            symbol=symbol,
            timeframe=timeframe,
            severity="info",
            detail={"deleted_rows": deleted_rows, "registry_deleted": registry_deleted},
        )
    except Exception as exc:
        await publish_ingestion_runtime_event(
            valkey_client,
            event_type=IngestionEventType.ASSET_PURGE_FAILED,
            symbol=symbol,
            timeframe=timeframe,
            severity="error",
            detail={"error": str(exc)},
        )
        raise DataIngestionError(
            f"Asset purge failed for {symbol}",
            context={"symbol": symbol, "timeframe": timeframe},
        ) from exc


async def scheduled_asset_cleanup(ctx: dict[str, Any]) -> None:
    janitor = IngestionStorageJanitor(DBPoolManager.get_writer_pool())
    for symbol, timeframe in await janitor.list_pending_removals():
        await purge_removed_asset(ctx, symbol, timeframe)


async def _clear_ingestion_observability_keys(
    valkey_client: Any | None,
    symbol: str,
    timeframe: str,
) -> None:
    if valkey_client is None:
        return
    keys = (
        IngestionCoordinator._state_key(symbol, timeframe),
        IngestionCoordinator._state_updated_ts_key(symbol, timeframe),
        IngestionCoordinator._disconnect_ts_key(symbol, timeframe),
        IngestionCoordinator._last_live_ts_key(symbol, timeframe),
        IngestionCoordinator._last_ready_ts_key(symbol, timeframe),
        IngestionCoordinator._disconnect_count_key(symbol, timeframe),
        IngestionCoordinator._resume_backfill_key(symbol, timeframe),
        asset_runtime_status_key(symbol, timeframe),
    )
    for key in keys:
        await valkey_client.delete(key)


async def _clear_ingestion_observability_keys_and_streams(
    valkey_client: Any | None,
    symbol: str,
    timeframe: str,
    *,
    publish_timeframes: list[str],
) -> None:
    await _clear_ingestion_observability_keys(valkey_client, symbol, timeframe)
    if valkey_client is None:
        return
    runtime_timeframes = _runtime_timeframes(timeframe, publish_timeframes)
    await valkey_client.delete(asset_manifest_key(symbol))
    for runtime_timeframe in runtime_timeframes:
        await valkey_client.delete(asset_timeframe_manifest_key(symbol, runtime_timeframe))
        await valkey_client.delete(f"stream:ohlcv:{symbol.lower()}:{runtime_timeframe}")
        await valkey_client.delete(_last_closed_published_key(symbol, runtime_timeframe))
        await valkey_client.delete(feature_stream_key(symbol, runtime_timeframe))
        await valkey_client.delete(price_update_stream_key(symbol, runtime_timeframe))
        await valkey_client.delete(f"signals:{str(symbol).upper().strip()}:{runtime_timeframe}")
    await valkey_client.delete(f"derivatives:latest:{str(symbol).upper().strip()}:oi")
    await valkey_client.delete(f"derivatives:latest:{str(symbol).upper().strip()}:funding")


def _runtime_timeframes(base_timeframe: str, publish_timeframes: list[str]) -> list[str]:
    ordered: list[str] = []
    for timeframe in [base_timeframe, *list(publish_timeframes)]:
        normalized = str(timeframe).strip()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return ordered


def _last_closed_published_key(symbol: str, timeframe: str) -> str:
    return f"{INGESTION_LAST_CLOSED_PUBLISHED_PREFIX}:{str(symbol).upper().strip()}:{str(timeframe).strip()}"
