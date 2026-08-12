"""Validated asset-file mutation and runtime replacement for ingestion."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import ValidationError

from apps.ingestion_app.runtime.controller import RuntimeController
from apps.ingestion_app.settings import (
    INGESTION_ASSET_CONFIG_NAMESPACE,
    INGESTION_CONFIG_NAMESPACE,
    AssetSettings,
    IngestionSettings,
)
from libs.common.config import ConfigManager

ASSET_NAMESPACE = INGESTION_ASSET_CONFIG_NAMESPACE


class AssetAlreadyExistsError(ValueError):
    """The requested asset file already exists."""


class AssetNotFoundError(LookupError):
    """The requested asset is not present in the last-known-good settings."""


class AssetCandidateError(ValueError):
    """The candidate asset or its runtime composition is invalid."""


class AssetOwnershipConfigurationError(AssetCandidateError):
    """An owned ingestion asset cannot silently relinquish lifecycle ownership."""


def _asset_code(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("asset must be a string")
    normalized = value.strip().upper()
    if not normalized:
        raise ValueError("asset must be non-empty")
    return normalized


def _deep_merge(base: dict[str, Any], updates: Mapping[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in updates.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, Mapping)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


async def _await_rollback(awaitable: Awaitable[object]) -> object:
    """Finish a rollback awaitable even if the caller was cancelled."""
    task = asyncio.create_task(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        raise


class AssetConfigService:
    """Own typed asset mutations and keep disk/runtime state aligned."""

    def __init__(
        self,
        *,
        config_manager: ConfigManager,
        runtime_controller: RuntimeController,
        on_asset_changed: Callable[[str], None] | None = None,
    ) -> None:
        if not isinstance(config_manager, ConfigManager):
            raise TypeError("config_manager must be ConfigManager")
        if not isinstance(runtime_controller, RuntimeController):
            raise TypeError("runtime_controller must be RuntimeController")
        self.config_manager = config_manager
        self.runtime_controller = runtime_controller
        self._on_asset_changed = on_asset_changed
        self._mutation_lock = asyncio.Lock()

    def list_assets(self) -> tuple[AssetSettings, ...]:
        settings = self.runtime_controller.settings
        return tuple(settings.assets[name] for name in sorted(settings.assets))

    def get_asset(self, asset: str) -> AssetSettings:
        code = _asset_code(asset)
        result = self.runtime_controller.settings.assets.get(code)
        if result is None:
            raise AssetNotFoundError(f"unknown asset: {code}")
        return result

    def _settings_from_config_manager(self) -> IngestionSettings:
        raw = self.config_manager.get(INGESTION_CONFIG_NAMESPACE)
        if not isinstance(raw, dict):
            raise TypeError("reloaded ingestion configuration is not a mapping")
        try:
            return IngestionSettings.model_validate(raw)
        except ValidationError as exc:
            raise RuntimeError("reloaded ingestion configuration is invalid") from exc

    def _candidate_settings(
        self,
        *,
        asset: AssetSettings,
    ) -> IngestionSettings:
        raw = copy.deepcopy(self.runtime_controller.settings.model_dump())
        raw["assets"][asset.asset] = asset.model_dump(mode="json")
        try:
            candidate = IngestionSettings.model_validate(raw)
        except ValidationError as exc:
            raise AssetCandidateError(
                "asset candidate is semantically invalid"
            ) from exc
        try:
            self.runtime_controller.validate_settings(candidate)
        except Exception as exc:
            raise AssetCandidateError(
                "asset candidate is incompatible with the runtime composition"
            ) from exc
        return candidate

    async def _apply_candidate(
        self,
        *,
        asset: AssetSettings,
        candidate: IngestionSettings,
        existed: bool,
        previous_asset: AssetSettings | None,
    ) -> AssetSettings:
        old_settings = self.runtime_controller.settings
        previous_contents = (
            previous_asset.model_dump(mode="json")
            if previous_asset is not None
            else None
        )
        contents = asset.model_dump(mode="json")

        try:
            self.config_manager.write_registered_directory_yaml(
                namespace=ASSET_NAMESPACE,
                filename=asset.asset,
                contents=contents,
                create_only=not existed,
            )
            reloaded = self._settings_from_config_manager()
            if reloaded != candidate:
                raise RuntimeError(
                    "reloaded asset configuration differs from the validated candidate"
                )
            await self.runtime_controller.replace_settings(reloaded)
        except asyncio.CancelledError:
            try:
                await self._rollback_mutation(
                    asset=asset,
                    existed=existed,
                    previous_contents=previous_contents,
                    old_settings=old_settings,
                )
            except BaseException as rollback_exc:
                raise RuntimeError(
                    "asset mutation cancellation rollback was incomplete"
                ) from rollback_exc
            raise
        except Exception as exc:
            try:
                await self._rollback_mutation(
                    asset=asset,
                    existed=existed,
                    previous_contents=previous_contents,
                    old_settings=old_settings,
                )
            except BaseException:  # noqa: BLE001
                raise RuntimeError(
                    "asset mutation failed and rollback was incomplete"
                ) from exc
            raise

        result = self.runtime_controller.settings.assets[asset.asset]
        if self._on_asset_changed is not None:
            self._on_asset_changed(result.asset)
        return result

    async def _rollback_mutation(
        self,
        *,
        asset: AssetSettings,
        existed: bool,
        previous_contents: dict[str, Any] | None,
        old_settings: IngestionSettings,
    ) -> None:
        """Restore disk/config state before restoring runtime settings."""
        rollback_errors: list[BaseException] = []
        try:
            if existed and previous_contents is not None:
                self.config_manager.write_registered_directory_yaml(
                    namespace=ASSET_NAMESPACE,
                    filename=asset.asset,
                    contents=previous_contents,
                    create_only=False,
                )
            else:
                self.config_manager._remove_registered_directory_yaml_for_rollback(
                    namespace=ASSET_NAMESPACE,
                    filename=asset.asset,
                )
        except BaseException as rollback_exc:  # noqa: BLE001
            rollback_errors.append(rollback_exc)

        try:
            await _await_rollback(
                self.runtime_controller.replace_settings(old_settings)
            )
        except BaseException as rollback_exc:  # noqa: BLE001
            rollback_errors.append(rollback_exc)

        if rollback_errors:
            raise RuntimeError("asset mutation rollback failed") from rollback_errors[0]

    async def create_asset(self, asset: AssetSettings) -> AssetSettings:
        async with self._mutation_lock:
            if not isinstance(asset, AssetSettings):
                raise TypeError("asset must be AssetSettings")
            current = self.runtime_controller.settings.assets.get(asset.asset)
            if current is not None:
                raise AssetAlreadyExistsError(f"asset already exists: {asset.asset}")
            candidate = self._candidate_settings(asset=asset)
            return await self._apply_candidate(
                asset=asset,
                candidate=candidate,
                existed=False,
                previous_asset=None,
            )

    async def patch_asset(
        self,
        asset: str,
        updates: Mapping[str, Any],
    ) -> AssetSettings:
        async with self._mutation_lock:
            code = _asset_code(asset)
            if not isinstance(updates, Mapping):
                raise AssetCandidateError("asset updates must be a mapping")
            if "asset" in updates:
                raise AssetCandidateError("asset identity cannot be changed")

            previous = self.get_asset(code)
            merged = _deep_merge(
                previous.model_dump(mode="json"),
                updates,
            )
            merged["asset"] = code
            if previous.owns_manifest_lifecycle and not merged.get(
                "owns_manifest_lifecycle",
                previous.owns_manifest_lifecycle,
            ):
                raise AssetOwnershipConfigurationError(
                    f"asset {code} cannot relinquish manifest/lifecycle ownership"
                )
            try:
                candidate_asset = AssetSettings.model_validate(merged)
            except ValidationError as exc:
                raise AssetCandidateError(
                    "asset patch is semantically invalid"
                ) from exc
            candidate = self._candidate_settings(asset=candidate_asset)
            return await self._apply_candidate(
                asset=candidate_asset,
                candidate=candidate,
                existed=True,
                previous_asset=previous,
            )


__all__ = [
    "ASSET_NAMESPACE",
    "AssetAlreadyExistsError",
    "AssetCandidateError",
    "AssetConfigService",
    "AssetNotFoundError",
    "AssetOwnershipConfigurationError",
]
