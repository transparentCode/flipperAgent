from __future__ import annotations

from typing import Any

from apps.ingestion_app.control_plane.repository import IngestionAssetRegistryRepository
from apps.ingestion_app.coordination import IngestionCoordinator
from apps.ingestion_app.events import publish_ingestion_runtime_event
from apps.ingestion_app.storage.janitor import IngestionStorageJanitor
from libs.common.db.pool_manager import DBPoolManager
from libs.common.exceptions import DataIngestionError
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
        IngestionCoordinator._disconnect_ts_key(symbol, timeframe),
        IngestionCoordinator._last_live_ts_key(symbol, timeframe),
        IngestionCoordinator._disconnect_count_key(symbol, timeframe),
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
    for publish_timeframe in (publish_timeframes or [timeframe]):
        await valkey_client.delete(f"stream:ohlcv:{symbol.lower()}:{publish_timeframe}")
