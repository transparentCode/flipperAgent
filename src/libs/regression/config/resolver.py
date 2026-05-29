from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

import yaml

from .schema import (
    AssetClassConfig,
    AssetConfig,
    AssetTimeframeConfig,
    GlobalConfig,
    OrchestratorConfig,
    PluginConfig,
    ResolvedPipelineConfig,
    TimeframeConfig,
    VolumeProfile,
)


class ConfigResolver:
    """Resolves 4-tier YAML config into ResolvedPipelineConfig per (asset, tf)."""

    def __init__(self, config: OrchestratorConfig) -> None:
        self._config = config
        self._cache: Dict[tuple, ResolvedPipelineConfig] = {}

    @classmethod
    def from_yaml(cls, path: str) -> "ConfigResolver":
        with open(path) as f:
            raw = yaml.safe_load(f)
        config = cls._parse_orchestrator(raw)
        return cls(config)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ConfigResolver":
        config = cls._parse_orchestrator(raw)
        return cls(config)

    @property
    def orchestrator_config(self) -> OrchestratorConfig:
        return self._config

    def resolve(self, asset: str, timeframe: str) -> ResolvedPipelineConfig:
        """Resolve the full config for a specific (asset, timeframe) pair.

        Resolution order: global → timeframe → asset_class → asset → asset.timeframes[tf]
        """
        key = (asset, timeframe)
        if key in self._cache:
            return self._cache[key]

        g = self._config.global_config
        tf_cfg = self._config.timeframes.get(timeframe, TimeframeConfig())
        asset_cfg = self._config.assets.get(asset, AssetConfig())
        asset_class_name = asset_cfg.asset_class
        ac_cfg = self._config.asset_classes.get(
            asset_class_name, AssetClassConfig()
        )
        atf_cfg = asset_cfg.timeframes.get(timeframe, AssetTimeframeConfig())

        # ── Scalar resolution: later tier wins ──
        window_size = _pick(
            atf_cfg.window_size,
            asset_cfg.window_size,
            tf_cfg.window_size,
            g.default_window_size,
        )
        trend_atr = _pick(atf_cfg.trend_atr_fraction, asset_cfg.trend_atr_fraction, tf_cfg.trend_atr_fraction, g.trend_atr_fraction)
        spread_atr = _pick(atf_cfg.spread_atr_fraction, asset_cfg.spread_atr_fraction, tf_cfg.spread_atr_fraction, g.spread_atr_fraction)
        momentum_atr = _pick(atf_cfg.momentum_atr_fraction, asset_cfg.momentum_atr_fraction, tf_cfg.momentum_atr_fraction, g.momentum_atr_fraction)
        neutral_slope = _pick(
            atf_cfg.neutral_slope_atr_fraction,
            asset_cfg.neutral_slope_atr_fraction,
            tf_cfg.neutral_slope_atr_fraction,
            g.neutral_slope_atr_fraction,
        )
        band_mult = _pick(atf_cfg.band_multiplier, asset_cfg.band_multiplier, tf_cfg.band_multiplier, g.band_multiplier)
        slope_accel = _pick(atf_cfg.slope_acceleration_alpha, tf_cfg.slope_acceleration_alpha, 0.0)

        # ── Plugin resolution: most specific non-None wins, else global ──
        features = _pick(ac_cfg.features, tf_cfg.features, g.features)
        methods_dict = _merge_methods(
            g.methods,
            tf_cfg.methods,
            ac_cfg.methods,
            asset_cfg.methods,
            atf_cfg.methods,
        )
        ensemble = _pick(
            atf_cfg.ensemble,
            asset_cfg.ensemble,
            ac_cfg.ensemble,
            tf_cfg.ensemble,
            g.ensemble,
        )
        uncertainty = _pick(tf_cfg.uncertainty, g.uncertainty)

        # ── Volume profile from asset class ──
        volume_profile = ac_cfg.volume_profile

        # ── MTF from asset config ──
        mtf_enabled = asset_cfg.mtf_enabled
        mtf_timeframes = tuple(asset_cfg.mtf_timeframes) if mtf_enabled else ()

        # ── Build frozen config ──
        methods_tuple = tuple(sorted(methods_dict.items()))
        features_tuple = tuple(features)

        config_hash = _compute_hash(
            asset, timeframe, window_size, trend_atr, spread_atr,
            momentum_atr, neutral_slope, band_mult, slope_accel,
            features_tuple, methods_tuple, ensemble, uncertainty,
        )

        resolved = ResolvedPipelineConfig(
            asset=asset,
            timeframe=timeframe,
            asset_class=asset_class_name,
            volume_profile=volume_profile,
            config_hash=config_hash,
            window_size=window_size,
            min_window=g.min_window,
            max_window=g.max_window,
            atr_period=g.atr_period,
            trend_atr_fraction=trend_atr,
            spread_atr_fraction=spread_atr,
            momentum_atr_fraction=momentum_atr,
            neutral_slope_atr_fraction=neutral_slope,
            band_multiplier=band_mult,
            slope_acceleration_alpha=slope_accel,
            features=features_tuple,
            methods=methods_tuple,
            ensemble=ensemble,
            uncertainty=uncertainty,
            session_gap_handling=ac_cfg.session_gap_handling,
            low_liquidity_window_handling=ac_cfg.low_liquidity_window_handling,
            regime_context_enabled=self._config.regime_context_enabled,
            regime_window_override=self._config.regime_window_override,
            mtf_enabled=mtf_enabled,
            mtf_timeframes=mtf_timeframes,
        )

        self._cache[key] = resolved
        return resolved

    def resolve_all(self, assets: list[str], timeframes: list[str]) -> Dict[tuple, ResolvedPipelineConfig]:
        """Resolve configs for all (asset, timeframe) combinations."""
        return {
            (a, tf): self.resolve(a, tf) for a in assets for tf in timeframes
        }

    # ── YAML Parsing ──

    @classmethod
    def _parse_orchestrator(cls, raw: Dict[str, Any]) -> OrchestratorConfig:
        orch = OrchestratorConfig()

        # Top-level orchestrator settings
        orch_raw = raw.get("orchestrator", {})
        if "mtf_timeframes" in orch_raw:
            orch.mtf_timeframes = orch_raw["mtf_timeframes"]
        if "tf_weights" in orch_raw:
            orch.tf_weights = orch_raw["tf_weights"]
        if "regime_context_enabled" in orch_raw:
            orch.regime_context_enabled = orch_raw["regime_context_enabled"]
        if "regime_window_override" in orch_raw:
            orch.regime_window_override = orch_raw["regime_window_override"]
        if "regime_window_defaults" in orch_raw:
            orch.regime_window_defaults = orch_raw["regime_window_defaults"]

        # Tier 1: Global
        g_raw = raw.get("global", {})
        orch.global_config = cls._parse_global(g_raw)

        # Tier 2: Timeframes
        for tf, tf_raw in raw.get("timeframes", {}).items():
            orch.timeframes[tf] = cls._parse_timeframe(tf_raw)

        # Tier 3: Asset classes
        for ac, ac_raw in raw.get("asset_classes", {}).items():
            orch.asset_classes[ac] = cls._parse_asset_class(ac_raw)

        # Tier 4: Assets
        for asset, a_raw in raw.get("assets", {}).items():
            orch.assets[asset] = cls._parse_asset(a_raw)

        # Optimization metadata
        if "optimization" in raw:
            orch.optimization = raw["optimization"]

        return orch

    @classmethod
    def _parse_global(cls, raw: Dict[str, Any]) -> GlobalConfig:
        g = GlobalConfig()
        for scalar in (
            "atr_period", "trend_atr_fraction", "spread_atr_fraction",
            "momentum_atr_fraction", "neutral_slope_atr_fraction",
            "band_multiplier", "min_window", "max_window", "default_window_size",
        ):
            if scalar in raw:
                setattr(g, scalar, raw[scalar])

        if "features" in raw:
            g.features = _parse_plugin_list(raw["features"])
        if "methods" in raw:
            g.methods = _parse_methods_dict(raw["methods"])
        if "ensemble" in raw:
            g.ensemble = _parse_single_plugin(raw["ensemble"])
        if "uncertainty" in raw:
            g.uncertainty = _parse_single_plugin(raw["uncertainty"])

        return g

    @classmethod
    def _parse_timeframe(cls, raw: Dict[str, Any]) -> TimeframeConfig:
        tf = TimeframeConfig()
        for scalar in (
            "window_size", "trend_atr_fraction", "spread_atr_fraction",
            "momentum_atr_fraction", "neutral_slope_atr_fraction",
            "band_multiplier", "slope_acceleration_alpha",
        ):
            if scalar in raw:
                setattr(tf, scalar, raw[scalar])
        if "features" in raw:
            tf.features = _parse_plugin_list(raw["features"])
        if "methods" in raw:
            tf.methods = _parse_methods_dict(raw["methods"])
        if "ensemble" in raw:
            tf.ensemble = _parse_single_plugin(raw["ensemble"])
        if "uncertainty" in raw:
            tf.uncertainty = _parse_single_plugin(raw["uncertainty"])
        return tf

    @classmethod
    def _parse_asset_class(cls, raw: Dict[str, Any]) -> AssetClassConfig:
        ac = AssetClassConfig()
        if "volume_profile" in raw:
            ac.volume_profile = VolumeProfile(raw["volume_profile"])
        if "session_gap_handling" in raw:
            ac.session_gap_handling = raw["session_gap_handling"]
        if "low_liquidity_window_handling" in raw:
            ac.low_liquidity_window_handling = raw["low_liquidity_window_handling"]
        if "features" in raw:
            ac.features = _parse_plugin_list(raw["features"])
        if "methods" in raw:
            ac.methods = _parse_methods_dict(raw["methods"])
        if "ensemble" in raw:
            ac.ensemble = _parse_single_plugin(raw["ensemble"])
        return ac

    @classmethod
    def _parse_asset(cls, raw: Dict[str, Any]) -> AssetConfig:
        a = AssetConfig()
        if "asset_class" in raw:
            a.asset_class = raw["asset_class"]
        if "mtf_enabled" in raw:
            a.mtf_enabled = raw["mtf_enabled"]
        if "mtf_timeframes" in raw:
            a.mtf_timeframes = raw["mtf_timeframes"]
        if "window_size" in raw:
            a.window_size = raw["window_size"]
        if "methods" in raw:
            a.methods = _parse_methods_dict(raw["methods"])
        if "ensemble" in raw:
            a.ensemble = _parse_single_plugin(raw["ensemble"])
        if "timeframes" in raw:
            for tf, tf_raw in raw["timeframes"].items():
                atf = AssetTimeframeConfig()
                for scalar in (
                    "window_size", "trend_atr_fraction", "spread_atr_fraction",
                    "momentum_atr_fraction", "neutral_slope_atr_fraction",
                    "band_multiplier", "slope_acceleration_alpha",
                ):
                    if scalar in tf_raw:
                        setattr(atf, scalar, tf_raw[scalar])
                if "methods" in tf_raw:
                    atf.methods = _parse_methods_dict(tf_raw["methods"])
                if "ensemble" in tf_raw:
                    atf.ensemble = _parse_single_plugin(tf_raw["ensemble"])
                a.timeframes[tf] = atf
        return a


# ── Helpers ──


def _pick(*values):
    """Return the first non-None value."""
    for v in values:
        if v is not None:
            return v
    return None


def _merge_methods(*layers: Optional[Dict[str, PluginConfig]]) -> Dict[str, PluginConfig]:
    """Merge method dicts across tiers. Later tiers override earlier per key, merging nested params."""
    merged: Dict[str, PluginConfig] = {}
    for layer in layers:
        if layer is not None:
            for name, cfg in layer.items():
                if name in merged:
                    existing = merged[name]
                    new_params = dict(existing.params)
                    new_params.update(cfg.params)
                    merged[name] = PluginConfig(
                        name=cfg.name,
                        enabled=cfg.enabled,
                        weight=cfg.weight,
                        params=new_params,
                    )
                else:
                    merged[name] = cfg
    return merged


def _parse_plugin_list(raw: list) -> list[PluginConfig]:
    result = []
    for item in raw:
        if isinstance(item, str):
            result.append(PluginConfig(name=item))
        elif isinstance(item, dict) and "name" in item:
            result.append(PluginConfig(
                name=item["name"],
                enabled=item.get("enabled", True),
                weight=item.get("weight", 1.0),
                params=item.get("params", {}),
            ))
    return result


def _parse_methods_dict(raw: dict) -> Dict[str, PluginConfig]:
    methods = {}
    for name, m_data in raw.items():
        if isinstance(m_data, dict):
            methods[name] = PluginConfig(
                name=name,
                enabled=m_data.get("enabled", True),
                weight=m_data.get("weight", 1.0),
                params=m_data.get("params", {}),
            )
        else:
            methods[name] = PluginConfig(name=name)
    return methods


def _parse_single_plugin(raw) -> PluginConfig:
    if isinstance(raw, str):
        return PluginConfig(name=raw)
    if isinstance(raw, dict):
        return PluginConfig(
            name=raw.get("name", ""),
            enabled=raw.get("enabled", True),
            weight=raw.get("weight", 1.0),
            params=raw.get("params", {}),
        )
    return PluginConfig(name=str(raw))


def _compute_hash(*args) -> str:
    """Deterministic hash from config parameters for provenance."""
    raw = json.dumps(str(args), sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]
