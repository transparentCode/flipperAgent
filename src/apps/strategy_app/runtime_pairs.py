"""Helpers for deriving effective strategy runtime pairs from config."""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.strategy_app.settings import create_strategy_config_manager
from apps.strategy_app.state import StrategyPair
from libs.common.asset_manifest import (
    AssetManifest,
)
from libs.common.config import ConfigManager
from libs.contracts.model_runtime import (
    derive_trigger_timeframe,
    iter_enabled_runtime_specs,
    validate_supported_runtime_spec,
)

_MODEL_ROOTS = ("models", "scoring_models", "strategy_models")


@dataclass
class _PairAccumulator:
    asset: str
    decision_timeframe: str
    trigger_timeframe: str
    base_timeframe: str
    trigger_mode: str
    source: str
    model_names: set[str] = field(default_factory=set)


def build_strategy_pairs(
    config_manager: ConfigManager | None = None,
    *,
    live_pairs: list[tuple[str, str]] | None = None,
    live_manifests: list[AssetManifest] | None = None,
) -> list[StrategyPair]:
    manager = create_strategy_config_manager(config_manager or ConfigManager())
    live_pair_set = {
        (str(asset).upper().strip(), str(timeframe).strip())
        for asset, timeframe in (live_pairs or [])
    }
    manifest_gate = _manifest_gate(live_manifests) if live_pairs is None else {}
    accumulators: dict[tuple[str, str, str], _PairAccumulator] = {}

    for normalized_asset in _iter_runtime_assets(manager):
        for runtime_spec in iter_enabled_runtime_specs(
            manager,
            asset=normalized_asset,
            roots=_MODEL_ROOTS,
        ):
            validate_supported_runtime_spec(
                runtime_spec,
                allow_decision_projection=True,
            )
            trigger_timeframe = derive_trigger_timeframe(runtime_spec)
            if (
                live_pair_set
                and (normalized_asset, trigger_timeframe) not in live_pair_set
            ):
                continue
            if manifest_gate and not manifest_gate.get(normalized_asset, True):
                continue
            pair_key = (
                normalized_asset,
                runtime_spec.decision_timeframe,
                trigger_timeframe,
            )
            source = (
                "asset_manifest"
                if live_pairs is not None or live_manifests is not None
                else "config"
            )
            accumulator = accumulators.get(pair_key)
            if accumulator is None:
                accumulator = _PairAccumulator(
                    asset=normalized_asset,
                    decision_timeframe=runtime_spec.decision_timeframe,
                    trigger_timeframe=trigger_timeframe,
                    base_timeframe=runtime_spec.base_timeframe,
                    trigger_mode=runtime_spec.trigger_mode,
                    source=source,
                )
                accumulators[pair_key] = accumulator
            if accumulator.base_timeframe != runtime_spec.base_timeframe:
                raise ValueError(
                    "Conflicting base_timeframe for strategy runtime pair "
                    f"{normalized_asset}/{runtime_spec.decision_timeframe}/{trigger_timeframe}: "
                    f"{accumulator.base_timeframe} vs {runtime_spec.base_timeframe}"
                )
            if accumulator.trigger_mode != runtime_spec.trigger_mode:
                raise ValueError(
                    "Conflicting trigger_mode for strategy runtime pair "
                    f"{normalized_asset}/{runtime_spec.decision_timeframe}/{trigger_timeframe}: "
                    f"{accumulator.trigger_mode} vs {runtime_spec.trigger_mode}"
                )
            accumulator.model_names.add(runtime_spec.model_name)

    pairs = [
        StrategyPair(
            asset=acc.asset,
            timeframe=acc.decision_timeframe,
            trigger_timeframe=acc.trigger_timeframe,
            base_timeframe=acc.base_timeframe,
            trigger_mode=acc.trigger_mode,
            model_names=sorted(acc.model_names),
            source=acc.source,
        )
        for acc in accumulators.values()
    ]
    pairs.sort(
        key=lambda pair: (
            pair.asset,
            pair.timeframe,
            pair.trigger_timeframe or pair.timeframe,
        )
    )
    return pairs


def _manifest_gate(manifests: list[AssetManifest] | None) -> dict[str, bool]:
    gate: dict[str, bool] = {}
    for manifest in manifests or []:
        gate[manifest.symbol] = bool(
            manifest.enabled and str(manifest.desired_state).upper() == "LIVE"
        )
    return gate


def _iter_runtime_assets(manager: ConfigManager) -> list[str]:
    assets: set[str] = set()
    for root_key in _MODEL_ROOTS:
        root = manager.get(root_key, {})
        root_assets = root.get("assets", {}) if isinstance(root, dict) else {}
        for asset, asset_cfg in root_assets.items():
            if asset == "default" or not isinstance(asset_cfg, dict):
                continue
            assets.add(str(asset).upper().strip())
    return sorted(assets)


__all__ = ["build_strategy_pairs"]
