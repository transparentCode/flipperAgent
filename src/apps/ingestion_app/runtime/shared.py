from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from apps.ingestion_app.models.asset_registry import (
    IngestionAssetDesiredState,
    IngestionAssetRecord,
)
from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)
config_manager = ConfigManager()


def track_task(task_registry: set[asyncio.Task[Any]], task: asyncio.Task[Any]) -> asyncio.Task[Any]:
    task_registry.add(task)
    task.add_done_callback(task_registry.discard)
    return task


@dataclass(frozen=True)
class AssetRuntimeSpec:
    symbol: str
    base_timeframe: str
    publish_timeframes: tuple[str, ...]
    enabled: bool
    desired_state: IngestionAssetDesiredState

    @classmethod
    def from_asset(cls, asset: IngestionAssetRecord) -> "AssetRuntimeSpec":
        return cls(
            symbol=asset.symbol,
            base_timeframe=asset.base_timeframe,
            publish_timeframes=tuple(sorted(asset.publish_timeframes)),
            enabled=asset.enabled,
            desired_state=asset.desired_state,
        )

    def should_run(self) -> bool:
        return self.enabled and self.desired_state == IngestionAssetDesiredState.LIVE


@dataclass
class AssetRuntimeHandle:
    spec: AssetRuntimeSpec
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)
