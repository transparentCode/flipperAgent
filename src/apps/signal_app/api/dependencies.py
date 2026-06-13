from __future__ import annotations

from typing import Any

from apps.signal_app.catalog import SignalPairCatalog
from apps.signal_app.observability.status import SignalObservabilityService
from apps.signal_app.pipeline.snapshot import FeatureSnapshotService
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client


class SignalApiDependencies:
    def __init__(
        self,
        *,
        config_manager: ConfigManager | None = None,
    ) -> None:
        self.config_manager = config_manager or ConfigManager()

    def catalog(self) -> SignalPairCatalog:
        return SignalPairCatalog(config_manager=self.config_manager)

    def snapshot_service(self) -> FeatureSnapshotService:
        return FeatureSnapshotService()

    async def open_observability(self) -> tuple[SignalObservabilityService, Any]:
        valkey_client = await create_valkey_client(self.config_manager)
        return SignalObservabilityService(valkey_client, self.catalog()), valkey_client


def get_signal_api_dependencies() -> SignalApiDependencies:
    return SignalApiDependencies()
