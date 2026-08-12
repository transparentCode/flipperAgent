from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest

from apps.ingestion_app.api.app import create_app
from apps.ingestion_app.runtime.controller import RuntimeController
from apps.ingestion_app.runtime.supervisor import (
    DesiredRuntimeState,
    RuntimeSnapshot,
    RuntimeState,
)
from apps.ingestion_app.services.config_reconciliation import AssetConfigService
from apps.ingestion_app.settings import (
    IngestionSettings,
    load_ingestion_settings,
)
from libs.common.config import ConfigManager
from tests.ingestion._asgi import request


class _InstantSupervisor:
    def __init__(self) -> None:
        self._snapshot = RuntimeSnapshot(
            desired_state=DesiredRuntimeState.RUNNING,
            state=RuntimeState.STOPPED,
            last_error=None,
        )

    async def run(self) -> None:
        self._snapshot = RuntimeSnapshot(
            desired_state=DesiredRuntimeState.RUNNING,
            state=RuntimeState.STOPPED,
            last_error=None,
        )

    def stop(self) -> None:
        pass

    def pause(self) -> None:
        self._snapshot = RuntimeSnapshot(
            desired_state=DesiredRuntimeState.PAUSED,
            state=RuntimeState.STOPPED,
            last_error=None,
        )

    def resume(self) -> None:
        pass

    def snapshot(self) -> RuntimeSnapshot:
        return self._snapshot

    async def execute_recovery(self, request) -> None:
        del request


def _test_asset(settings: IngestionSettings) -> dict[str, object]:
    raw = copy.deepcopy(settings.assets["BTC"].model_dump(mode="json"))
    raw["asset"] = "ADA"
    instrument = raw["instruments"].pop("BTC-USDT-PERP")
    instrument["base_asset"] = "ADA"
    raw["instruments"] = {"ADA-USDT-PERP": instrument}
    return raw


@pytest.mark.asyncio
async def test_api_asset_mutation_reconciles_temporary_config_and_remaining_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    repository_root = Path(__file__).parents[3]
    shutil.copytree(
        repository_root / "configs" / "ingestion",
        tmp_path / "configs" / "ingestion",
    )
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(tmp_path / "configs"))
    settings = load_ingestion_settings(manager)
    created: list[IngestionSettings] = []

    def factory(candidate: IngestionSettings) -> _InstantSupervisor:
        created.append(candidate)
        return _InstantSupervisor()

    controller = RuntimeController(settings=settings, supervisor_factory=factory)
    service = AssetConfigService(
        config_manager=manager,
        runtime_controller=controller,
    )
    app = create_app(runtime_controller=controller, config_service=service)

    try:
        created_response = await request(app, "POST", "/assets", _test_asset(settings))
        assert created_response.status_code == 201
        assert (await request(app, "GET", "/assets/ADA")).status_code == 200
        assert (tmp_path / "configs/ingestion/assets/ADA.yaml").exists()
        assert (
            await request(app, "POST", "/assets", _test_asset(settings))
        ).status_code == 409
        assert (
            await request(
                app,
                "PATCH",
                "/assets/UNKNOWN",
                {"updates": {"enabled": False}},
            )
        ).status_code == 404
        assert (
            await request(
                app,
                "PATCH",
                "/assets/ADA",
                {"updates": {"asset": "ETH"}},
            )
        ).status_code == 422

        disabled = await request(
            app,
            "PATCH",
            "/assets/ADA",
            {"updates": {"enabled": False}},
        )
        assert disabled.status_code == 200
        assert disabled.body["enabled"] is False

        disabled_btc = await request(
            app,
            "PATCH",
            "/assets/BTC",
            {"updates": {"enabled": False}},
        )
        assert disabled_btc.status_code == 200
        # N2B2 keeps the other five migrated assets enabled while BTC and the
        # temporary ADA asset are disabled.
        assert (await request(app, "GET", "/runtime")).body["enabled_asset_count"] == 5

        reenabled = await request(
            app,
            "PATCH",
            "/assets/ADA",
            {"updates": {"enabled": True}},
        )
        assert reenabled.status_code == 200
        assert reenabled.body["enabled"] is True
        assert (await request(app, "GET", "/assets/ADA")).body["enabled"] is True
    finally:
        await controller.close()
        manager.shutdown()
        ConfigManager.reset_singleton()

    assert created
