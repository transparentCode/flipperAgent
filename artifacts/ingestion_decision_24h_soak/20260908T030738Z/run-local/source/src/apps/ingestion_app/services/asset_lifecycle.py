"""Ingestion-owned asset manifest and lifecycle reconciliation."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from time import time
from typing import Any

from apps.ingestion_app.settings import AssetSettings, IngestionSettings
from libs.common.asset_manifest import (
    AssetLifecycleEvent,
    AssetManifest,
    AssetManifestStore,
    AssetTimeframeManifest,
    lifecycle_event_type,
)
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.ingestion import IngestionCommandType

_LOGGER = bind_logger(__name__)
MANIFEST_SOURCE = "ingestion"
DEFAULT_RECONCILER_RETRY_BACKOFF_SECONDS = 0.5


def _desired_state(asset: AssetSettings) -> str:
    return "LIVE" if asset.enabled else "STOPPED"


def _single_instrument(asset: AssetSettings) -> tuple[str, Any]:
    if len(asset.instruments) != 1:
        raise ValueError(
            f"ingestion manifest ownership currently requires one instrument for {asset.asset}"
        )
    return next(iter(asset.instruments.items()))


def _manifest_state(manifest: AssetManifest) -> dict[str, Any]:
    """Return stable semantic state, excluding publication timestamps."""
    state = manifest.model_dump(mode="json")
    state.pop("updated_at", None)
    state.pop("request_id", None)
    return state


def make_lifecycle_event_id(
    *,
    manifest: AssetManifest,
    command_type: IngestionCommandType,
) -> str:
    """Build an idempotent event ID for the canonical ingestion lifecycle."""
    raw = json.dumps(
        {
            "source": MANIFEST_SOURCE,
            "symbol": manifest.symbol,
            "command_type": command_type.value,
            "manifest": _manifest_state(manifest),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class AssetLifecycleService:
    """Translate one ingestion asset definition into normalized control-plane state."""

    def build_manifests(
        self,
        asset: AssetSettings,
        settings: IngestionSettings,
        *,
        updated_at: float | None = None,
    ) -> tuple[AssetManifest, list[AssetTimeframeManifest]]:
        instrument_id, instrument = _single_instrument(asset)
        del instrument_id
        provider_symbol = instrument.provider_symbols[instrument.live_provider]
        timestamp = updated_at if updated_at is not None else time()
        timeframes = list(instrument.timeframes)
        publish_timeframes = [
            timeframe
            for timeframe in timeframes
            if timeframe != settings.base_timeframe
        ]
        state = _desired_state(asset)
        common = {
            "symbol": provider_symbol,
            "exchange": instrument.venue,
            "provider": instrument.live_provider,
            "base_timeframe": settings.base_timeframe,
            "historical_backfill_days": 0,
            "retention_days": None,
            "enabled": asset.enabled,
            "desired_state": state,
            "asset_version": 1,
            "timeframe_version": 1,
            "updated_at": timestamp,
            "source": MANIFEST_SOURCE,
        }
        manifest = AssetManifest(
            **common,
            publish_timeframes=publish_timeframes,
            timeframes=timeframes,
        )
        timeframe_manifests = [
            AssetTimeframeManifest(
                **common,
                timeframe=timeframe,
                is_base_timeframe=timeframe == settings.base_timeframe,
            )
            for timeframe in timeframes
        ]
        return manifest, timeframe_manifests

    async def reconcile_asset(
        self,
        *,
        asset: AssetSettings,
        settings: IngestionSettings,
        manifest_store: AssetManifestStore,
        updated_at: float | None = None,
    ) -> AssetLifecycleEvent | None:
        """Converge one owned asset and emit only a semantic state transition."""
        desired, timeframe_manifests = self.build_manifests(
            asset,
            settings,
            updated_at=updated_at,
        )
        previous = await manifest_store.read_asset(desired.symbol)
        if previous is not None and previous.source == MANIFEST_SOURCE:
            if _manifest_state(previous) == _manifest_state(desired):
                if await self._has_retained_event(manifest_store, desired):
                    return None
                command_type = IngestionCommandType.UPSERT_ASSET
            else:
                command_type = self._transition_for_existing(previous, desired)
            takeover = False
        else:
            command_type = IngestionCommandType.UPSERT_ASSET
            takeover = previous is not None

        await manifest_store.sync_manifest(
            desired,
            timeframe_manifests,
            allow_source_takeover=takeover,
        )
        event = AssetLifecycleEvent(
            event_id=make_lifecycle_event_id(
                manifest=desired,
                command_type=command_type,
            ),
            event_type=lifecycle_event_type(command_type),
            command_type=command_type.value,
            symbol=desired.symbol,
            exchange=desired.exchange,
            provider=desired.provider,
            base_timeframe=desired.base_timeframe,
            publish_timeframes=list(desired.publish_timeframes),
            timeframes=list(desired.timeframes),
            enabled=desired.enabled,
            desired_state=desired.desired_state,
            asset_version=desired.asset_version,
            timeframe_version=desired.timeframe_version,
            requested_by=MANIFEST_SOURCE,
            reason="ingestion_manifest_reconciliation",
            emitted_at=desired.updated_at,
            source=MANIFEST_SOURCE,
        )
        await manifest_store.publish_event(event)
        return event

    async def _has_retained_event(
        self,
        manifest_store: AssetManifestStore,
        manifest: AssetManifest,
    ) -> bool:
        candidate_commands = [IngestionCommandType.UPSERT_ASSET]
        candidate_commands.append(
            IngestionCommandType.RESUME_ASSET
            if manifest.enabled and manifest.desired_state == "LIVE"
            else IngestionCommandType.STOP_ASSET
        )
        candidate_commands.append(IngestionCommandType.UPDATE_ASSET)
        for command_type in candidate_commands:
            present = await manifest_store.has_lifecycle_event(
                make_lifecycle_event_id(
                    manifest=manifest,
                    command_type=command_type,
                )
            )
            if present is None or present:
                return True
        return False

    @staticmethod
    def _transition_for_existing(
        previous: AssetManifest,
        desired: AssetManifest,
    ) -> IngestionCommandType:
        if (
            previous.enabled != desired.enabled
            or previous.desired_state != desired.desired_state
        ):
            return (
                IngestionCommandType.RESUME_ASSET
                if desired.enabled and desired.desired_state == "LIVE"
                else IngestionCommandType.STOP_ASSET
            )
        return IngestionCommandType.UPDATE_ASSET


SettingsProvider = Callable[[], IngestionSettings]


class AssetLifecycleReconciler:
    """Event-driven ingestion lifecycle reconciler bound to the current broker client."""

    def __init__(
        self,
        *,
        settings_provider: SettingsProvider,
        manifest_store: AssetManifestStore | None = None,
        service: AssetLifecycleService | None = None,
        retry_backoff_seconds: float = DEFAULT_RECONCILER_RETRY_BACKOFF_SECONDS,
    ) -> None:
        self._settings_provider = settings_provider
        self._manifest_store = manifest_store
        self._service = service or AssetLifecycleService()
        self._retry_backoff_seconds = max(0.01, float(retry_backoff_seconds))
        self._dirty_assets: set[str] = set()
        self._wake_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    def bind_manifest_store(self, manifest_store: AssetManifestStore) -> None:
        self._manifest_store = manifest_store

    def mark_dirty(self, asset: str) -> None:
        """Mark a definition for asynchronous reconciliation without I/O."""
        self._dirty_assets.add(str(asset).upper().strip())
        self._wake_event.set()

    def mark_all_managed_dirty(self) -> None:
        settings = self._settings_provider()
        for asset in settings.assets.values():
            if asset.owns_manifest_lifecycle:
                self._dirty_assets.add(asset.asset)
        self._wake_event.set()

    async def reconcile_all(self) -> list[AssetLifecycleEvent]:
        settings = self._settings_provider()
        events: list[AssetLifecycleEvent] = []
        for asset in settings.assets.values():
            if not asset.owns_manifest_lifecycle:
                continue
            event = await self._reconcile_one(asset, settings)
            if event is not None:
                events.append(event)
        return events

    async def _reconcile_one(
        self,
        asset: AssetSettings,
        settings: IngestionSettings,
    ) -> AssetLifecycleEvent | None:
        if self._manifest_store is None:
            raise RuntimeError("manifest store is not bound")
        async with self._lock:
            return await self._service.reconcile_asset(
                asset=asset,
                settings=settings,
                manifest_store=self._manifest_store,
            )

    async def _run_dirty(self) -> None:
        while True:
            await self._wake_event.wait()
            self._wake_event.clear()
            while self._dirty_assets:
                asset_name = self._dirty_assets.pop()
                settings = self._settings_provider()
                asset = settings.assets.get(asset_name)
                if asset is None or not asset.owns_manifest_lifecycle:
                    continue
                try:
                    await self._reconcile_one(asset, settings)
                except asyncio.CancelledError:
                    self._dirty_assets.add(asset_name)
                    raise
                except Exception:
                    self._dirty_assets.add(asset_name)
                    _LOGGER.warning(
                        "ingestion lifecycle reconciliation failed for %s",
                        asset_name,
                        exc_info=True,
                    )
                    await asyncio.sleep(self._retry_backoff_seconds)
                    self._wake_event.set()
                    break

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._run_dirty(),
                name="ingestion-asset-lifecycle-reconciler",
            )

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


__all__ = [
    "MANIFEST_SOURCE",
    "AssetLifecycleReconciler",
    "AssetLifecycleService",
    "make_lifecycle_event_id",
]
