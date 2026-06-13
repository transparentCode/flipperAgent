from __future__ import annotations

import asyncio
from typing import Any

import arq

from apps.ingestion_app.constants import INGESTION_CONTROL_STREAM
from apps.ingestion_app.coordination import IngestionCoordinator, IngestionState
from apps.ingestion_app.events import publish_ingestion_runtime_event
from apps.ingestion_app.control_plane import IngestionAssetCatalog
from apps.ingestion_app.models.asset_registry import IngestionAssetDesiredState, IngestionAssetRecord
from apps.ingestion_app.runtime.bootstrap import initialize_asset_runtime
from apps.ingestion_app.runtime.shared import (
    AssetRuntimeHandle,
    AssetRuntimeSpec,
    logger,
    track_task,
)
from libs.common.config import ConfigManager
from libs.contracts.schemas import IngestionEventType


class IngestionRuntimeReconciler:
    def __init__(
        self,
        *,
        config_manager: ConfigManager,
        arq_pool: arq.connections.ArqRedis,
        coordinator: IngestionCoordinator,
        redis_client: Any,
        asset_catalog: IngestionAssetCatalog | None = None,
    ) -> None:
        self.config_manager = config_manager
        self.arq_pool = arq_pool
        self.coordinator = coordinator
        self.redis_client = redis_client
        self.asset_catalog = asset_catalog or IngestionAssetCatalog(config_manager=config_manager)
        self.asset_handles: dict[str, AssetRuntimeHandle] = {}
        self.pending_removals: set[str] = set()
        self.control_stream_last_id = "$"
        self.reconcile_interval_seconds = float(
            self.config_manager.get("ingestion.runtime.reconcile_interval_seconds", 5)
        )

    async def run(self) -> None:
        while True:
            await self.reconcile_once()
            await self.wait_for_change()

    async def reconcile_once(self) -> None:
        assets = await self.asset_catalog.list_effective_assets()
        desired_by_symbol = {asset.symbol: asset for asset in assets}
        self.pending_removals.intersection_update(
            {
                asset.symbol
                for asset in assets
                if asset.desired_state == IngestionAssetDesiredState.REMOVING
            }
        )

        for symbol, handle in list(self.asset_handles.items()):
            desired = desired_by_symbol.get(symbol)
            if desired is None:
                await self.stop_asset(symbol, handle)
                continue

            desired_spec = AssetRuntimeSpec.from_asset(desired)
            if desired.desired_state == IngestionAssetDesiredState.REMOVING or not desired_spec.should_run():
                await self.stop_asset(symbol, handle)
                continue

            if not handle.tasks or handle.spec != desired_spec:
                await self.stop_asset(symbol, handle)

        for symbol, asset in desired_by_symbol.items():
            desired_spec = AssetRuntimeSpec.from_asset(asset)
            if asset.desired_state == IngestionAssetDesiredState.REMOVING:
                await self.dispatch_asset_removal(asset)
                continue
            if not desired_spec.should_run():
                continue
            if symbol in self.asset_handles:
                continue
            await self.start_asset(asset, desired_spec)

    async def stop(self) -> None:
        for symbol, handle in list(self.asset_handles.items()):
            await self.stop_asset(symbol, handle)

    async def start_asset(self, asset: IngestionAssetRecord, spec: AssetRuntimeSpec) -> None:
        handle = AssetRuntimeHandle(spec=spec)
        bootstrap_task = asyncio.create_task(
            initialize_asset_runtime(asset, self.arq_pool, self.coordinator, handle.tasks)
        )
        track_task(handle.tasks, bootstrap_task)
        self.asset_handles[asset.symbol] = handle
        logger.info(
            f"[{asset.symbol}] Runtime started "
            f"(publish_timeframes={list(spec.publish_timeframes)}, base_timeframe={spec.base_timeframe})"
        )

    async def stop_asset(self, symbol: str, handle: AssetRuntimeHandle) -> None:
        self.asset_handles.pop(symbol, None)
        for task in list(handle.tasks):
            task.cancel()
        if handle.tasks:
            await asyncio.gather(*handle.tasks, return_exceptions=True)
        try:
            await self.coordinator.transition(symbol, handle.spec.base_timeframe, IngestionState.COLD)
        except Exception:
            logger.warning(f"[{symbol}] Failed to transition runtime to COLD during stop", exc_info=True)
        logger.info(f"[{symbol}] Runtime stopped")

    async def dispatch_asset_removal(self, asset: IngestionAssetRecord) -> None:
        if asset.symbol in self.pending_removals:
            return

        try:
            await self.arq_pool.enqueue_job("purge_removed_asset", asset.symbol, asset.base_timeframe)
            self.pending_removals.add(asset.symbol)
            logger.info(f"[{asset.symbol}] Dispatched asset purge job")
        except Exception as exc:
            logger.warning(f"[{asset.symbol}] Failed to dispatch asset purge job: {exc}", exc_info=True)
            await publish_ingestion_runtime_event(
                self.redis_client,
                event_type=IngestionEventType.ASSET_PURGE_FAILED,
                symbol=asset.symbol,
                timeframe=asset.base_timeframe,
                severity="error",
                detail={"error": str(exc), "phase": "dispatch"},
            )

    async def wait_for_change(self) -> None:
        stream_wait_ms = max(250, int(self.reconcile_interval_seconds * 1000))
        xread = getattr(self.redis_client, "xread", None)
        if not callable(xread):
            await asyncio.sleep(self.reconcile_interval_seconds)
            return

        try:
            response = await xread(
                {INGESTION_CONTROL_STREAM: self.control_stream_last_id},
                count=10,
                block=stream_wait_ms,
            )
            if not response or not isinstance(response, (list, tuple)):
                return
            for _stream_name, messages in response:
                if messages:
                    self.control_stream_last_id = messages[-1][0]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"Runtime control stream wait failed: {exc}", exc_info=True)
            await asyncio.sleep(self.reconcile_interval_seconds)
