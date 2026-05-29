"""Ingestion observability router."""

from __future__ import annotations

from fastapi import APIRouter

from apps.ingestion_app.coordination import IngestionCoordinator
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client

router = APIRouter(prefix="/ingestion", tags=["ingestion"])

config_manager = ConfigManager()


@router.get("/status", summary="Per-asset ingestion observability snapshot")
async def ingestion_status() -> dict:
    """Return state, last_live_ts, last_disconnect_ts, and disconnects_in_window
    for every configured asset/timeframe pair.

    Creates a short-lived Valkey connection per request — suitable for low-frequency
    operational polling (not a hot path).
    """
    target_assets = config_manager.get("ingestion.assets.target_list", ["BTCUSDT"])
    base_timeframe = config_manager.get("ingestion.timeframes.base_gap_fill", "1m")

    valkey_client = await create_valkey_client(config_manager)
    try:
        coordinator = IngestionCoordinator(valkey_client, config_manager)
        snapshots = {}
        for symbol in target_assets:
            snapshots[f"{symbol}:{base_timeframe}"] = await coordinator.get_observability_snapshot(
                symbol, base_timeframe
            )
    finally:
        await valkey_client.aclose()

    return snapshots
