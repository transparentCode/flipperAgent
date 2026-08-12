from __future__ import annotations

import asyncio
import copy
import shutil
from pathlib import Path

import pytest

from apps.ingestion_app.runtime.supervisor import (
    DesiredRuntimeState,
    RuntimeSnapshot,
    RuntimeState,
)
from apps.ingestion_app.services.config_reconciliation import (
    AssetAlreadyExistsError,
    AssetCandidateError,
    AssetConfigService,
    AssetOwnershipConfigurationError,
)
from apps.ingestion_app.settings import (
    AssetSettings,
    IngestionSettings,
    load_ingestion_settings,
)
from libs.common.config import ConfigManager


class _FakeSupervisor:
    def __init__(self) -> None:
        self._snapshot = RuntimeSnapshot(
            desired_state=DesiredRuntimeState.RUNNING,
            state=RuntimeState.STOPPED,
            last_error=None,
        )
        self._stop_event = asyncio.Event()

    async def run(self) -> None:
        self._snapshot = RuntimeSnapshot(
            desired_state=DesiredRuntimeState.RUNNING,
            state=RuntimeState.STARTING,
            last_error=None,
        )
        await self._stop_event.wait()
        self._snapshot = RuntimeSnapshot(
            desired_state=self._snapshot.desired_state,
            state=RuntimeState.STOPPED,
            last_error=self._snapshot.last_error,
        )

    def stop(self) -> None:
        self._stop_event.set()

    def pause(self) -> None:
        self._snapshot = RuntimeSnapshot(
            desired_state=DesiredRuntimeState.PAUSED,
            state=RuntimeState.STOPPED,
            last_error=None,
        )

    def resume(self) -> None:
        self._snapshot = RuntimeSnapshot(
            desired_state=DesiredRuntimeState.RUNNING,
            state=self._snapshot.state,
            last_error=self._snapshot.last_error,
        )

    def snapshot(self) -> RuntimeSnapshot:
        return self._snapshot

    async def execute_recovery(self, request) -> None:
        del request


@pytest.fixture
def ingestion_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    repository_root = Path(__file__).parents[3]
    shutil.copytree(
        repository_root / "configs" / "ingestion",
        tmp_path / "configs" / "ingestion",
    )
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(tmp_path / "configs"))
    settings = load_ingestion_settings(manager)
    yield manager, settings
    manager.shutdown()
    ConfigManager.reset_singleton()


def _controller(settings: IngestionSettings):
    from apps.ingestion_app.runtime.controller import RuntimeController

    created: list[_FakeSupervisor] = []

    def factory(candidate: IngestionSettings) -> _FakeSupervisor:
        del candidate
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    return RuntimeController(settings=settings, supervisor_factory=factory), created


def _test_asset(settings: IngestionSettings) -> AssetSettings:
    raw = copy.deepcopy(settings.assets["BTC"].model_dump(mode="json"))
    raw["asset"] = "ADA"
    instrument = raw["instruments"].pop("BTC-USDT-PERP")
    instrument["base_asset"] = "ADA"
    raw["instruments"] = {"ADA-USDT-PERP": instrument}
    return AssetSettings.model_validate(raw)


@pytest.mark.asyncio
async def test_patch_disable_retains_yaml_and_updates_lkg(ingestion_config) -> None:
    manager, settings = ingestion_config
    controller, _ = _controller(settings)
    service = AssetConfigService(
        config_manager=manager,
        runtime_controller=controller,
    )

    result = await service.patch_asset("btc", {"enabled": False})

    assert result.enabled is False
    assert controller.settings.assets["BTC"].enabled is False
    assert (Path("configs/ingestion/assets/BTC.yaml")).exists()
    assert manager.get("ingestion.assets.BTC.enabled") is False


@pytest.mark.asyncio
async def test_owned_asset_cannot_relinquish_manifest_lifecycle_ownership(
    ingestion_config,
) -> None:
    manager, settings = ingestion_config
    controller, _ = _controller(settings)
    service = AssetConfigService(
        config_manager=manager,
        runtime_controller=controller,
    )

    with pytest.raises(AssetOwnershipConfigurationError):
        await service.patch_asset("BTC", {"owns_manifest_lifecycle": False})

    assert controller.settings.assets["BTC"].owns_manifest_lifecycle is True


@pytest.mark.asyncio
async def test_create_asset_is_atomic_and_duplicate_create_is_rejected(
    ingestion_config,
) -> None:
    manager, settings = ingestion_config
    controller, created = _controller(settings)
    service = AssetConfigService(
        config_manager=manager,
        runtime_controller=controller,
    )
    test_asset = _test_asset(settings)

    result = await service.create_asset(test_asset)

    assert result.asset == "ADA"
    assert controller.settings.assets["ADA"].asset == "ADA"
    assert manager.get("ingestion.assets.ADA.asset") == "ADA"
    with pytest.raises(AssetAlreadyExistsError):
        await service.create_asset(test_asset)

    await controller.close()
    assert created


@pytest.mark.asyncio
async def test_invalid_patch_does_not_touch_disk(ingestion_config) -> None:
    manager, settings = ingestion_config
    controller, _ = _controller(settings)
    service = AssetConfigService(
        config_manager=manager,
        runtime_controller=controller,
    )
    before = Path("configs/ingestion/assets/BTC.yaml").read_bytes()

    with pytest.raises(AssetCandidateError):
        await service.patch_asset(
            "BTC", {"instruments": {"BTC-USDT-PERP": {"timeframes": ["2h"]}}}
        )

    assert Path("configs/ingestion/assets/BTC.yaml").read_bytes() == before
    assert (
        controller.settings.assets["BTC"].instruments["BTC-USDT-PERP"].timeframes[-1]
        == "1w"
    )


@pytest.mark.asyncio
async def test_runtime_failure_rolls_back_asset_file_and_settings(
    ingestion_config, monkeypatch
) -> None:
    manager, settings = ingestion_config
    controller, _ = _controller(settings)
    service = AssetConfigService(
        config_manager=manager,
        runtime_controller=controller,
    )
    original_replace = controller.replace_settings
    calls = 0

    async def fail_first(candidate: IngestionSettings):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic replacement failure")
        return await original_replace(candidate)

    monkeypatch.setattr(controller, "replace_settings", fail_first)

    with pytest.raises(RuntimeError, match="synthetic replacement failure"):
        await service.patch_asset("BTC", {"enabled": False})

    assert calls == 2
    assert controller.settings.assets["BTC"].enabled is True
    assert manager.get("ingestion.assets.BTC.enabled") is True


@pytest.mark.asyncio
async def test_cancelled_patch_rolls_back_disk_config_and_runtime(
    ingestion_config,
    monkeypatch,
) -> None:
    manager, settings = ingestion_config
    controller, created = _controller(settings)
    service = AssetConfigService(
        config_manager=manager,
        runtime_controller=controller,
    )
    await controller.start()
    original_bytes = Path("configs/ingestion/assets/BTC.yaml").read_bytes()

    write_completed = asyncio.Event()
    original_write = manager.write_registered_directory_yaml

    def write_and_signal(**kwargs):
        result = original_write(**kwargs)
        if kwargs["contents"].get("enabled") is False:
            write_completed.set()
        return result

    monkeypatch.setattr(
        manager,
        "write_registered_directory_yaml",
        write_and_signal,
    )

    await controller._operation_lock.acquire()
    mutation = asyncio.create_task(service.patch_asset("BTC", {"enabled": False}))
    try:
        await write_completed.wait()
        assert manager.get("ingestion.assets.BTC.enabled") is False
        assert controller.settings.assets["BTC"].enabled is True
        mutation.cancel()
    finally:
        controller._operation_lock.release()

    with pytest.raises(asyncio.CancelledError):
        await mutation

    assert Path("configs/ingestion/assets/BTC.yaml").read_bytes() == original_bytes
    assert manager.get("ingestion.assets.BTC.enabled") is True
    assert controller.settings.assets["BTC"].enabled is True
    assert controller.is_started is True
    # With the six-asset production configuration, candidate validation also
    # builds a supervisor because five other assets remain enabled.
    assert len(created) == 3
    assert not list(Path("configs/ingestion/assets").glob(".*.tmp"))
    await controller.close()
