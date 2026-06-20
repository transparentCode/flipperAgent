from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from libs.common.asset_manifest import (
    AssetManifest,
    iter_live_manifest_timeframes,
    live_manifest_pairs,
)
from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_FEATURES, CONFIG_FILE_MODELS
from libs.contracts.model_runtime import (
    ResolvedModelRuntimeSpec,
    derive_trigger_timeframe,
    iter_enabled_runtime_specs,
    validate_supported_runtime_spec,
)

from apps.signal_app.models import SignalPair


@dataclass
class _PairAccumulator:
    asset: str
    timeframe: str
    trigger_timeframe: str
    trigger_mode: str
    base_timeframe: str
    source: str
    required_context_profiles: set[str] = field(default_factory=set)


def build_signal_pairs(
    config_manager: ConfigManager | None = None,
    *,
    live_pairs: list[tuple[str, str]] | None = None,
    live_manifests: list[AssetManifest] | None = None,
) -> list[SignalPair]:
    manager = config_manager or ConfigManager()
    manager.register_file(CONFIG_FILE_MODELS)
    manager.register_file(CONFIG_FILE_FEATURES)
    if live_pairs is None and live_manifests:
        live_pairs = live_manifest_pairs(live_manifests)
    live_pair_set = {
        (str(asset).upper().strip(), str(timeframe).strip())
        for asset, timeframe in (live_pairs or [])
    }
    accumulators: dict[tuple[str, str, str], _PairAccumulator] = {}
    base_pair_profiles: dict[tuple[str, str], set[str]] = defaultdict(set)

    for normalized_asset in _iter_runtime_assets(manager):
        for runtime_spec in iter_enabled_runtime_specs(
            manager,
            asset=normalized_asset,
            roots=("models", "scoring_models", "strategy_models"),
        ):
            validate_supported_runtime_spec(
                runtime_spec,
                allow_decision_projection=True,
            )
            if runtime_spec.required_context_profiles and _pair_is_live(
                live_pair_set,
                normalized_asset,
                runtime_spec.base_timeframe,
            ):
                base_pair_profiles[(normalized_asset, runtime_spec.base_timeframe)].update(
                    runtime_spec.required_context_profiles
                )
            decision_timeframe = runtime_spec.decision_timeframe
            trigger_timeframe = derive_trigger_timeframe(runtime_spec)
            if live_pair_set and (normalized_asset, trigger_timeframe) not in live_pair_set:
                continue
            pair_key = (normalized_asset, decision_timeframe, trigger_timeframe)
            source = "asset_manifest" if live_pair_set else "runtime"
            accumulator = accumulators.get(pair_key)
            if accumulator is None:
                accumulator = _PairAccumulator(
                    asset=normalized_asset,
                    timeframe=decision_timeframe,
                    trigger_timeframe=trigger_timeframe,
                    trigger_mode=runtime_spec.trigger_mode,
                    base_timeframe=runtime_spec.base_timeframe,
                    source=source,
                )
                accumulators[pair_key] = accumulator
            _merge_runtime_spec_into_accumulator(accumulator, runtime_spec)

    pairs = [
        SignalPair(
            asset=acc.asset,
            timeframe=acc.timeframe,
            trigger_timeframe=(
                None if acc.trigger_timeframe == acc.timeframe else acc.trigger_timeframe
            ),
            trigger_mode=acc.trigger_mode,
            base_timeframe=acc.base_timeframe,
            required_context_profiles=sorted(acc.required_context_profiles),
            source=acc.source,
        )
        for acc in accumulators.values()
    ]

    for (asset, base_timeframe), profiles in base_pair_profiles.items():
        pair = SignalPair(
            asset=asset,
            timeframe=base_timeframe,
            trigger_timeframe=None,
            trigger_mode="on_bar_close",
            base_timeframe=base_timeframe,
            required_context_profiles=sorted(profiles),
            source="asset_manifest" if live_pair_set else "runtime_base",
        )
        if all(existing.key != pair.key for existing in pairs):
            pairs.append(pair)
            continue
        for existing in pairs:
            if existing.key != pair.key:
                continue
            merged = list(existing.required_context_profiles)
            for profile in pair.required_context_profiles:
                if profile not in merged:
                    merged.append(profile)
            existing.required_context_profiles = merged
            break

    _append_manifest_fallback_pairs(pairs, live_manifests)

    pairs.sort(key=lambda pair: (pair.asset, pair.timeframe, pair.trigger_timeframe or pair.timeframe))
    return pairs


def _iter_runtime_assets(manager: ConfigManager) -> list[str]:
    assets: set[str] = set()
    for root_key in ("models", "scoring_models", "strategy_models"):
        root = manager.get(root_key, {})
        root_assets = root.get("assets", {}) if isinstance(root, dict) else {}
        for asset, asset_config in root_assets.items():
            if asset == "default" or not isinstance(asset_config, dict):
                continue
            assets.add(str(asset).upper().strip())
    return sorted(assets)


def _pair_is_live(
    live_pair_set: set[tuple[str, str]],
    asset: str,
    timeframe: str,
) -> bool:
    if not live_pair_set:
        return True
    return (asset, timeframe) in live_pair_set


def _merge_runtime_spec_into_accumulator(
    accumulator: _PairAccumulator,
    runtime_spec: ResolvedModelRuntimeSpec,
) -> None:
    base_timeframe = str(runtime_spec.base_timeframe).strip() or "1m"
    trigger_mode = str(runtime_spec.trigger_mode).strip() or "on_bar_close"
    if accumulator.base_timeframe != base_timeframe:
        raise ValueError(
            f"Conflicting base_timeframe for {accumulator.asset}:{accumulator.timeframe}: "
            f"{accumulator.base_timeframe} vs {base_timeframe}"
        )
    if accumulator.trigger_mode != trigger_mode:
        raise ValueError(
            f"Conflicting trigger_mode for {accumulator.asset}:{accumulator.timeframe}: "
            f"{accumulator.trigger_mode} vs {trigger_mode}"
        )
    for profile in runtime_spec.required_context_profiles:
        normalized = str(profile).strip()
        if normalized:
            accumulator.required_context_profiles.add(normalized)
def _append_manifest_fallback_pairs(
    pairs: list[SignalPair],
    manifests: list[AssetManifest] | None,
) -> None:
    existing_keys = {pair.key for pair in pairs}
    for manifest, timeframe in iter_live_manifest_timeframes(manifests):
        pair = SignalPair(
            asset=manifest.symbol,
            timeframe=timeframe,
            trigger_mode="on_bar_close",
            base_timeframe=manifest.base_timeframe,
            source="asset_manifest",
        )
        if pair.key in existing_keys:
            continue
        pairs.append(pair)
        existing_keys.add(pair.key)


__all__ = ["build_signal_pairs"]
