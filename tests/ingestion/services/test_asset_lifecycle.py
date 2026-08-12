from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from time import monotonic

import pytest

from apps.ingestion_app.services.asset_lifecycle import (
    MANIFEST_SOURCE,
    AssetLifecycleReconciler,
    AssetLifecycleService,
)
from apps.ingestion_app.settings import load_ingestion_settings
from libs.common.asset_manifest import (
    AssetLifecycleEvent,
    AssetLifecycleEventType,
    AssetManifest,
    AssetManifestOwnershipError,
    AssetManifestStore,
)
from libs.common.config import ConfigManager
from libs.contracts.ingestion import IngestionCommandType


class _FakeValkey:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.events: list[dict[str, str]] = []

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def hset(self, key: str, mapping: dict[str, str]) -> int:
        self.hashes[key] = dict(mapping)
        return len(mapping)

    async def delete(self, key: str) -> int:
        self.hashes.pop(key, None)
        return 1

    async def xadd(self, stream: str, payload: dict[str, str], **kwargs: object) -> str:
        del stream, kwargs
        self.events.append(dict(payload))
        return f"{len(self.events)}-0"

    async def xrange(self, stream: str, minimum: str, maximum: str):
        del stream, minimum, maximum
        return [
            (
                f"{index}-0".encode(),
                {key.encode(): value.encode() for key, value in payload.items()},
            )
            for index, payload in enumerate(self.events, start=1)
        ]


class _FailOnceLifecycleService:
    def __init__(self) -> None:
        self.calls = 0

    async def reconcile_asset(self, **kwargs: object) -> None:
        del kwargs
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient lifecycle failure")


class _AlwaysFailLifecycleService:
    def __init__(self) -> None:
        self.calls = 0
        self.call_times: list[float] = []

    async def reconcile_asset(self, **kwargs: object) -> None:
        del kwargs
        self.calls += 1
        self.call_times.append(monotonic())
        raise RuntimeError("persistent lifecycle failure")


@pytest.fixture
def ingestion_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    repository_root = Path(__file__).parents[3]
    shutil.copytree(
        repository_root / "configs" / "ingestion",
        tmp_path / "configs" / "ingestion",
    )
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(tmp_path / "configs"))
    settings = load_ingestion_settings(manager)
    yield settings
    manager.shutdown()
    ConfigManager.reset_singleton()


def _foreign_manifest() -> AssetManifest:
    return AssetManifest(
        symbol="BTCUSDT",
        timeframes=["1m", "1h", "4h"],
        publish_timeframes=["1h", "4h"],
        source="other_source",
        updated_at=1.0,
    )


def test_ingestion_asset_ownership_config_is_six_asset_final_state(
    ingestion_settings,
) -> None:
    assert all(
        asset_settings.enabled for asset_settings in ingestion_settings.assets.values()
    )
    assert all(
        asset_settings.owns_manifest_lifecycle
        for asset_settings in ingestion_settings.assets.values()
    )


@pytest.mark.asyncio
async def test_ingestion_reconcile_takes_over_once_and_is_idempotent(
    ingestion_settings,
) -> None:
    valkey = _FakeValkey()
    store = AssetManifestStore(valkey)
    await store.sync_manifest(_foreign_manifest())
    service = AssetLifecycleService()
    btc = ingestion_settings.assets["BTC"]

    event = await service.reconcile_asset(
        asset=btc,
        settings=ingestion_settings,
        manifest_store=store,
        updated_at=10.0,
    )

    assert event is not None
    assert event.event_type is AssetLifecycleEventType.ASSET_UPSERTED
    assert event.command_type == IngestionCommandType.UPSERT_ASSET.value
    assert event.source == MANIFEST_SOURCE
    assert (await store.read_asset("BTCUSDT")).source == MANIFEST_SOURCE
    assert len(valkey.events) == 1

    assert (
        await service.reconcile_asset(
            asset=btc,
            settings=ingestion_settings,
            manifest_store=store,
            updated_at=11.0,
        )
        is None
    )
    assert len(valkey.events) == 1


@pytest.mark.asyncio
async def test_ingestion_reconcile_emits_stop_and_resume_from_enabled_state(
    ingestion_settings,
) -> None:
    valkey = _FakeValkey()
    store = AssetManifestStore(valkey)
    service = AssetLifecycleService()
    btc = ingestion_settings.assets["BTC"]

    await service.reconcile_asset(
        asset=btc,
        settings=ingestion_settings,
        manifest_store=store,
        updated_at=10.0,
    )
    stopped = btc.model_copy(update={"enabled": False})
    stop_event = await service.reconcile_asset(
        asset=stopped,
        settings=ingestion_settings,
        manifest_store=store,
        updated_at=20.0,
    )
    assert stop_event is not None
    assert stop_event.event_type is AssetLifecycleEventType.ASSET_STOPPED

    resume_event = await service.reconcile_asset(
        asset=btc,
        settings=ingestion_settings,
        manifest_store=store,
        updated_at=30.0,
    )
    assert resume_event is not None
    assert resume_event.event_type is AssetLifecycleEventType.ASSET_RESUMED
    assert len(valkey.events) == 3


@pytest.mark.asyncio
async def test_ingestion_reconcile_repairs_missing_retained_lifecycle_event(
    ingestion_settings,
) -> None:
    valkey = _FakeValkey()
    store = AssetManifestStore(valkey)
    service = AssetLifecycleService()
    btc = ingestion_settings.assets["BTC"]
    manifest, timeframe_manifests = service.build_manifests(btc, ingestion_settings)

    await store.sync_manifest(manifest, timeframe_manifests)
    event = await service.reconcile_asset(
        asset=btc,
        settings=ingestion_settings,
        manifest_store=store,
        updated_at=10.0,
    )

    assert event is not None
    assert event.event_type is AssetLifecycleEventType.ASSET_UPSERTED
    assert len(valkey.events) == 1
    assert (
        await service.reconcile_asset(
            asset=btc,
            settings=ingestion_settings,
            manifest_store=store,
            updated_at=11.0,
        )
        is None
    )
    assert len(valkey.events) == 1


@pytest.mark.asyncio
async def test_manifest_store_blocks_cross_source_write_and_event(
    ingestion_settings,
) -> None:
    del ingestion_settings
    valkey = _FakeValkey()
    store = AssetManifestStore(valkey)
    await store.sync_manifest(_foreign_manifest())
    ingestion_manifest = _foreign_manifest().model_copy(
        update={"source": MANIFEST_SOURCE}
    )

    with pytest.raises(AssetManifestOwnershipError):
        await store.sync_manifest(ingestion_manifest)

    event = AssetLifecycleEvent(
        event_id="ingestion-event",
        event_type=AssetLifecycleEventType.ASSET_UPDATED,
        command_type=IngestionCommandType.UPDATE_ASSET.value,
        symbol="BTCUSDT",
        source=MANIFEST_SOURCE,
        emitted_at=2.0,
    )
    with pytest.raises(AssetManifestOwnershipError):
        await store.publish_event(event)

    await store.sync_manifest(ingestion_manifest, allow_source_takeover=True)
    with pytest.raises(AssetManifestOwnershipError):
        await store.sync_manifest(_foreign_manifest())
    foreign_event = event.model_copy(
        update={"event_id": "foreign-event", "source": "other_source"}
    )
    with pytest.raises(AssetManifestOwnershipError):
        await store.publish_event(foreign_event)
    assert valkey.events == []


@pytest.mark.asyncio
async def test_reconciler_dirty_mark_is_nonblocking_and_collapses_duplicates(
    ingestion_settings,
) -> None:
    valkey = _FakeValkey()
    store = AssetManifestStore(valkey)
    reconciler = AssetLifecycleReconciler(
        settings_provider=lambda: ingestion_settings,
        manifest_store=store,
    )
    await reconciler.reconcile_all()
    assert len(valkey.events) == 6
    assert {event["symbol"] for event in valkey.events} == {
        "BTCUSDT",
        "ETHUSDT",
        "XRPUSDT",
        "SOLUSDT",
        "BNBUSDT",
        "DOGEUSDT",
    }

    await reconciler.start()
    reconciler.mark_dirty("BTC")
    reconciler.mark_dirty("BTC")
    await asyncio.sleep(0.05)
    await reconciler.stop()

    assert len(valkey.events) == 6


async def _wait_until(predicate, *, timeout: float = 1.0) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition did not become true before timeout")


@pytest.mark.asyncio
async def test_reconciler_rearms_after_transient_failure(ingestion_settings) -> None:
    service = _FailOnceLifecycleService()
    reconciler = AssetLifecycleReconciler(
        settings_provider=lambda: ingestion_settings,
        manifest_store=object(),
        service=service,
        retry_backoff_seconds=0.01,
    )

    await reconciler.start()
    reconciler.mark_dirty("BTC")
    try:
        await _wait_until(
            lambda: service.calls == 2 and not reconciler._dirty_assets,
        )
        assert service.calls == 2
        assert reconciler._task is not None
        assert not reconciler._task.done()
    finally:
        await asyncio.wait_for(reconciler.stop(), timeout=0.5)


@pytest.mark.asyncio
async def test_reconciler_persistent_failure_is_bounded_and_cancellable(
    ingestion_settings,
) -> None:
    service = _AlwaysFailLifecycleService()
    retry_backoff = 0.03
    reconciler = AssetLifecycleReconciler(
        settings_provider=lambda: ingestion_settings,
        manifest_store=object(),
        service=service,
        retry_backoff_seconds=retry_backoff,
    )

    await reconciler.start()
    reconciler.mark_dirty("BTC")
    try:
        await asyncio.sleep(0.12)
        assert service.calls >= 2
        assert service.calls < 20
        assert reconciler._dirty_assets == {"BTC"}
        assert reconciler._task is not None
        assert not reconciler._task.done()
        assert all(
            later - earlier >= retry_backoff * 0.6
            for earlier, later in zip(service.call_times, service.call_times[1:])
        )
    finally:
        await asyncio.wait_for(reconciler.stop(), timeout=0.5)
