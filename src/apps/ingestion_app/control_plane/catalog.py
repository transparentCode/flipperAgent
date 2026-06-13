from __future__ import annotations

from typing import Any

import asyncpg

from apps.ingestion_app.control_plane.repository import IngestionAssetRegistryRepository
from apps.ingestion_app.models.asset_registry import (
    IngestionAssetDesiredState,
    IngestionAssetRecord,
    IngestionAssetSource,
)
from libs.common.config import ConfigManager
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)


class IngestionAssetCatalog:
    def __init__(
        self,
        *,
        config_manager: ConfigManager | Any | None = None,
        pool: asyncpg.Pool | None = None,
    ) -> None:
        self.config_manager = config_manager or ConfigManager()
        self.pool = pool

    async def list_effective_assets(self) -> list[IngestionAssetRecord]:
        config_assets = {asset.symbol: asset for asset in self._assets_from_config()}
        registry_assets = await self._load_registry_assets()
        if not registry_assets:
            return list(config_assets.values())

        for asset in registry_assets:
            config_assets[asset.symbol] = asset
        return [config_assets[symbol] for symbol in sorted(config_assets)]

    async def get_effective_asset(self, symbol: str) -> IngestionAssetRecord | None:
        symbol = symbol.upper()
        registry_asset = await self._load_registry_asset(symbol)
        if registry_asset is not None:
            return registry_asset

        for asset in self._assets_from_config():
            if asset.symbol == symbol:
                return asset
        return None

    async def _load_registry_assets(self) -> list[IngestionAssetRecord]:
        try:
            pool = self.pool or DBPoolManager.get_reader_pool()
        except RuntimeError as exc:
            logger.warning(f"Registry DB pool unavailable; falling back to config assets: {exc}")
            return []

        repo = IngestionAssetRegistryRepository(pool)
        try:
            return await repo.list_assets()
        except asyncpg.PostgresError as exc:
            logger.warning(f"Registry table unavailable or unreadable; falling back to config assets: {exc}")
            return []

    async def _load_registry_asset(self, symbol: str) -> IngestionAssetRecord | None:
        try:
            pool = self.pool or DBPoolManager.get_reader_pool()
        except RuntimeError as exc:
            logger.warning(f"Registry DB pool unavailable; falling back to config assets: {exc}")
            return None

        repo = IngestionAssetRegistryRepository(pool)
        try:
            return await repo.get_asset(symbol)
        except asyncpg.PostgresError as exc:
            logger.warning(f"Registry table unavailable or unreadable; falling back to config assets: {exc}")
            return None

    def _assets_from_config(self) -> list[IngestionAssetRecord]:
        target_assets = self.config_manager.get("ingestion.assets.target_list", ["BTCUSDT"])
        publish_timeframes = self.config_manager.get("ingestion.assets.publish_timeframes", {})
        base_timeframe = self.config_manager.get("ingestion.timeframes.base_gap_fill", "1m")
        historical_backfill_days = int(
            self.config_manager.get("ingestion.assets.historical_backfill_days", 2)
        )

        return [
            IngestionAssetRecord(
                symbol=symbol,
                exchange="binance",
                provider="binance_native",
                base_timeframe=base_timeframe,
                publish_timeframes=publish_timeframes.get(symbol, []),
                historical_backfill_days=historical_backfill_days,
                enabled=True,
                desired_state=IngestionAssetDesiredState.LIVE,
                source=IngestionAssetSource.CONFIG,
            )
            for symbol in target_assets
        ]
