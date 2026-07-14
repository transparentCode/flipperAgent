"""
S/R Config Resolver + Rule-Derived Params Calculator
=====================================================
4-tier config cascade and formula-based parameter derivation.

Resolution order (highest wins):
  1. Asset metadata profile defaults
  2. Global ``sr.*`` config
  3. Per-TF ``per_tf.{tf}.*`` overrides
  4. Per-asset ``assets.{symbol}.defaults.*`` and ``assets.{symbol}.{tf}.*``
  5. Rule-derived formulas (explicit config overrides rule-derived)
"""

from __future__ import annotations

import copy
import math
import logging
import warnings
from dataclasses import dataclass, fields
from typing import Any, Dict, List, Optional

from app.sr.models import (
    AssetCharacteristics,
    AssetMetadata,
    RuleDerivedParams,
)
from app.sr.config_schema import (
    EnsembleConfig,
    EnhancementConfig,
    FeaturesConfig,
    LifecycleConfig,
    OptimizationConfig,
    OptimizationParameterConfig,
    PipelineConfig,
    RegimeConfig,
    RuleDerivedConfig,
    SRResolvedConfig,
)

logger = logging.getLogger("app.sr.config")

_SIDECAR_PIPELINE_FALLBACKS: Dict[str, float] = {
    "merge_threshold_pct_atr": 0.25,
    "dedup_proximity_atr": 0.5,
    "zone_half_width_atr": 0.1,
}

_SIDECAR_LIFECYCLE_FALLBACKS: Dict[str, float | int] = {
    "breakout_atr_threshold": 0.3,
    "touch_proximity_atr": 0.1,
    "false_breakout_recovery_bars": 6,
}

_SIDECAR_ENHANCEMENT_FALLBACKS: Dict[str, float] = {
    "volume_spike_threshold": 1.5,
}

_ZONE_HALF_WIDTH_KERNELS = (
    "pivot_hl",
    "volume_poc",
    "regression_band",
    "liquidity_sweep",
)

_TIMEFRAME_MINUTES: Dict[str, int] = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "8h": 480,
    "12h": 720,
    "1d": 1440,
    "3d": 4320,
    "1w": 10080,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _coalesce(value, fallback):
    """Return *value* unless it is None, in which case return *fallback*.

    Unlike ``value or fallback``, this correctly preserves 0, 0.0,
    and other falsy-but-intentional values.
    """
    return fallback if value is None else value


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge *overlay* into *base* (returns new dict)."""
    result = copy.deepcopy(base)
    for key, val in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def _dict_to_frozen(cls, data: dict):
    """Instantiate a frozen dataclass from a dict, ignoring unknown keys."""
    valid = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in valid})


def _normalize_enabled_kernels(pipeline_config: dict) -> dict:
    """Normalize legacy kernel aliases to runtime-supported kernel names."""
    enabled = list(pipeline_config.get("enabled_kernels", []))
    if not enabled:
        return pipeline_config

    normalized: List[str] = []
    saw_volume_hvn = False
    for kernel_name in enabled:
        canonical_name = kernel_name
        if kernel_name == "volume_hvn":
            canonical_name = "volume_poc"
            saw_volume_hvn = True

        if canonical_name not in normalized:
            normalized.append(canonical_name)

    if saw_volume_hvn:
        warnings.warn(
            "Legacy kernel 'volume_hvn' is normalized to 'volume_poc'; "
            "HVN candidates are emitted by VolumePOCKernel metadata, not a standalone kernel.",
            RuntimeWarning,
            stacklevel=3,
        )

    result = dict(pipeline_config)
    result["enabled_kernels"] = normalized
    return result


_KERNEL_PARAM_ALIASES: Dict[str, Dict[str, str]] = {
    "pivot_hl": {
        "score_vol_weight": "vol_factor_weight",
        "score_dominance_weight": "dominance_weight",
    },
    "fair_value_gap": {
        "score_atr_cap": "max_gap_atr_cap",
        "filled_score_discount": "filled_penalty_multiplier",
    },
    "session_gap": {
        "score_atr_cap": "max_gap_atr_cap",
    },
    "fractal_channel": {
        "boundary_buffer": "boundary_buffer_atr",
        "midline_score_discount": "midline_strength_factor",
    },
}


def _normalize_kernel_param_aliases(merged_config: dict) -> dict:
    """Normalize legacy kernel parameter aliases to canonical runtime names."""
    result = copy.deepcopy(merged_config)
    kernels = copy.deepcopy(result.get("kernels", {}))
    consumed_alias_messages: List[str] = []

    for kernel_name, alias_map in _KERNEL_PARAM_ALIASES.items():
        params = kernels.get(kernel_name)
        if not isinstance(params, dict):
            continue

        normalized = dict(params)
        for legacy_name, canonical_name in alias_map.items():
            if legacy_name not in normalized:
                continue

            legacy_path = f"sr.kernels.{kernel_name}.{legacy_name}"
            canonical_path = f"sr.kernels.{kernel_name}.{canonical_name}"

            if canonical_name not in normalized:
                normalized[canonical_name] = normalized[legacy_name]
                consumed_alias_messages.append(
                    f"Legacy config key '{legacy_path}' is deprecated; use '{canonical_path}' instead.",
                )
            else:
                consumed_alias_messages.append(
                    f"Legacy config key '{legacy_path}' is deprecated and ignored because '{canonical_path}' is present.",
                )
            normalized.pop(legacy_name, None)

        kernels[kernel_name] = normalized

    if consumed_alias_messages:
        warnings.warn(
            " ".join(consumed_alias_messages),
            DeprecationWarning,
            stacklevel=3,
        )

    result["kernels"] = kernels
    return result


def _normalize_legacy_ensemble_method(merged_config: dict) -> dict:
    """Promote legacy pipeline.ensemble_method into ensemble.method."""
    result = copy.deepcopy(merged_config)
    pipeline_config = dict(result.get("pipeline", {}))
    ensemble_config = dict(result.get("ensemble", {}))

    legacy_present = "ensemble_method" in pipeline_config
    legacy_method = pipeline_config.pop("ensemble_method", None)
    if legacy_present and "method" not in ensemble_config:
        ensemble_config["method"] = legacy_method
    if legacy_present:
        warnings.warn(
            "Legacy config key 'sr.pipeline.ensemble_method' is deprecated; "
            "use 'sr.ensemble.method' instead.",
            DeprecationWarning,
            stacklevel=3,
        )

    result["pipeline"] = pipeline_config
    result["ensemble"] = ensemble_config
    return result


# ---------------------------------------------------------------------------
# Rule-Derived Params Calculator
# ---------------------------------------------------------------------------

class RuleDerivedParamsCalculator:
    """
    Compute rule-derived defaults from asset characteristics.

    ALL formula coefficients come from config (``sr.rule_derived`` section).
    No hardcoded magic numbers.
    """

    def __init__(self, formula_config: RuleDerivedConfig):
        self._cfg = formula_config

    def compute(self, chars: AssetCharacteristics) -> RuleDerivedParams:
        tf_ratio = chars.tf_minutes / 60.0
        p = self._cfg.pivot

        # Pivot lookback
        n1 = int(_clip(round(p.base_multiplier * math.sqrt(tf_ratio)), p.n1_min, p.n1_max))
        n2 = int(_clip(round(p.n2_ratio * n1), p.n2_min, p.n2_max))

        # Hurst with stability guard
        hf = self._cfg.hurst_fallback
        hurst = chars.hurst if chars.hurst_confidence >= hf.min_confidence else hf.fallback_value

        # Zone width
        zw = self._cfg.zone_width

        # Breakout timing
        bk = self._cfg.breakout
        confirm_bars = int(_clip(
            round(bk.base_multiplier * math.sqrt(tf_ratio)),
            bk.confirm_min,
            bk.confirm_max,
        ))

        # Volume spike
        vs = self._cfg.volume_spike

        # Max zones
        mz = self._cfg.max_zones

        # Fractal
        fr = self._cfg.fractal

        # Wick adaptation
        wa = self._cfg.wick_adaptation
        wick_excess = max(0.0, chars.wick_body_ratio - wa.neutral_wick)

        # Spatial thresholds (data-derived from microstructure percentiles)
        merge_threshold = max(0.15, chars.wick_p75_atr * 0.5)
        dedup_proximity = max(0.3, chars.wick_p75_atr)
        zone_half_width = max(0.05, chars.wick_p75_atr * 0.25)

        # Temporal adaptation (timeframe-normalized inactivity)
        ia = self._cfg.inactivity
        tf_hours = chars.tf_minutes / 60.0
        inactivity_bars = int(_clip(
            ia.base_inactivity_hours / tf_hours,
            ia.min_inactivity_bars,
            ia.max_inactivity_bars,
        ))
        # Per-bar decay = 1 - (1 - hourly_rate) ^ hours_per_bar
        # This makes the calendar-time decay curve identical across timeframes
        inactivity_decay = 1.0 - (1.0 - ia.base_decay_per_hour) ** tf_hours

        return RuleDerivedParams(
            n1=n1,
            n2=n2,
            fractal_period=fr.period_multiplier * n1,
            fractal_buffer=fr.buffer_atr_fraction * chars.atr,
            round_interval=self._round_interval(chars.price, chars.metadata),
            max_zone_width_atr=_clip(
                zw.base_atr + zw.hurst_sensitivity * abs(hurst - 0.5),
                zw.atr_min,
                zw.atr_max,
            ),
            max_zone_width_pct=_clip(
                zw.pct_multiplier * chars.atr_pct * 100,
                zw.pct_min,
                zw.pct_max,
            ),
            breakout_confirm_bars=confirm_bars,
            false_breakout_window=bk.false_breakout_multiplier * confirm_bars,
            inactivity_threshold=inactivity_bars,
            inactivity_decay=inactivity_decay,
            max_active_zones=int(_clip(
                round(mz.base_multiplier * math.sqrt(chars.n_timeframes)),
                mz.min,
                mz.max,
            )),
            volume_spike_threshold=_clip(
                1.0 + chars.volume_kurtosis / vs.kurtosis_divisor,
                vs.floor,
                vs.ceiling,
            ),
            breakout_atr_threshold=wa.base_breakout_atr + wa.breakout_scaling * wick_excess,
            touch_proximity_atr=wa.base_touch_proximity_atr + wa.touch_scaling * wick_excess,
            false_breakout_recovery_bars=wa.base_recovery_bars + int(round(wa.recovery_scaling * wick_excess)),
            merge_threshold_pct_atr=merge_threshold,
            dedup_proximity_atr=dedup_proximity,
            zone_half_width_atr=zone_half_width,
            vp_lookback_hours=list(chars.metadata.session_lookback_hours),
        )

    def _round_interval(self, price: float, metadata: AssetMetadata) -> float:
        if price <= 0:
            return 1.0
        if metadata.round_number_mode == "pip":
            if price < 2.0:
                return 0.01
            if price < 200.0:
                return 1.0
            return 10.0
        # Default: decimal magnitude
        return 10 ** (math.floor(math.log10(price)) - 1)


# ---------------------------------------------------------------------------
# Config Resolver
# ---------------------------------------------------------------------------

# Default asset-metadata profiles (used when config omits profiles section)
_DEFAULT_PROFILES: Dict[str, Dict[str, Any]] = {
    "crypto": {
        "trading_hours_per_day": 24.0,
        "trading_days_per_week": 7,
        "has_session_gaps": False,
        "gap_breakout_policy": "gap_ignored",
        "gap_escalation_atr": 999.0,
        "session_lookback_hours": [24, 168, 720],
        "round_number_mode": "decimal",
        "ex_dividend_filter": False,
        "continuous_market": True,
    },
    "equity": {
        "trading_hours_per_day": 6.5,
        "trading_days_per_week": 5,
        "has_session_gaps": True,
        "gap_breakout_policy": "gap_suspends_countdown",
        "gap_escalation_atr": 3.0,
        "session_lookback_hours": [7, 33, 137],
        "round_number_mode": "decimal",
        "ex_dividend_filter": True,
        "continuous_market": False,
    },
    "fx": {
        "trading_hours_per_day": 24.0,
        "trading_days_per_week": 5,
        "has_session_gaps": False,
        "gap_breakout_policy": "gap_ignored",
        "gap_escalation_atr": 999.0,
        "session_lookback_hours": [24, 120, 504],
        "round_number_mode": "pip",
        "ex_dividend_filter": False,
        "continuous_market": True,
    },
    "commodity": {
        "trading_hours_per_day": 8.0,
        "trading_days_per_week": 5,
        "has_session_gaps": True,
        "gap_breakout_policy": "gap_suspends_countdown",
        "gap_escalation_atr": 3.0,
        "session_lookback_hours": [8, 40, 168],
        "round_number_mode": "decimal",
        "ex_dividend_filter": False,
        "continuous_market": False,
    },
    "futures": {
        "trading_hours_per_day": 23.0,
        "trading_days_per_week": 5,
        "has_session_gaps": True,
        "gap_breakout_policy": "gap_suspends_countdown",
        "gap_escalation_atr": 3.0,
        "session_lookback_hours": [23, 115, 483],
        "round_number_mode": "decimal",
        "ex_dividend_filter": False,
        "continuous_market": False,
    },
}


class SRConfigResolver:
    """
    Resolves configuration for a given (symbol, timeframe) pair.

    Resolution order:
      1. Load asset_metadata profile + per-asset metadata overrides → AssetMetadata
      2. Load ``sr.*`` global defaults
      3. Overlay ``per_tf.{tf}.*`` overrides
      4. Overlay ``assets.{symbol}.defaults.*`` overrides
      5. Overlay ``assets.{symbol}.{tf}.*`` overrides
      6. Compute rule-derived params (configurable coefficients from merged config)
      7. Merge rule-derived as defaults (explicit config wins)
      8. Return frozen ``SRResolvedConfig``
    """

    def resolve_optimization_config(self, raw_config: dict) -> Dict[str, Any]:
        """Extract the global optimizer config without affecting runtime resolve()."""
        sr_config = copy.deepcopy(raw_config.get("sr", {}))
        top_level_global = {
            key: value
            for key, value in raw_config.items()
            if key not in {"asset_metadata", "sr", "per_tf", "assets"}
        }
        if top_level_global:
            sr_config = _deep_merge(sr_config, top_level_global)

        optimization = sr_config.get("optimization", {})
        return copy.deepcopy(optimization) if isinstance(optimization, dict) else {}

    def resolve_typed_optimization_config(self, raw_config: dict) -> OptimizationConfig:
        """Build a typed optimizer config from ``sr.optimization``."""
        raw_optimization = self.resolve_optimization_config(raw_config)
        raw_parameters = raw_optimization.get("parameters", {})
        parameters: Dict[str, OptimizationParameterConfig] = {}

        if isinstance(raw_parameters, dict):
            for name, raw_param in raw_parameters.items():
                if not isinstance(raw_param, dict):
                    continue
                parameters[name] = OptimizationParameterConfig(
                    low=float(raw_param["low"]) if "low" in raw_param else None,
                    high=float(raw_param["high"]) if "high" in raw_param else None,
                    kind=str(raw_param.get("kind", "float")),
                    enabled=bool(raw_param.get("enabled", True)),
                    metadata_gate=raw_param.get("metadata_gate"),
                )

        return OptimizationConfig(
            n_trials=int(raw_optimization.get("n_trials", OptimizationConfig.n_trials)),
            timeout_s=float(raw_optimization.get("timeout_s", OptimizationConfig.timeout_s)),
            tier6_weight=float(raw_optimization.get("tier6_weight", OptimizationConfig.tier6_weight)),
            stage1_eval_bars=int(raw_optimization.get("stage1_eval_bars", OptimizationConfig.stage1_eval_bars)),
            parameters=parameters,
            per_asset_n_trials=int(raw_optimization.get("per_asset_n_trials", OptimizationConfig.per_asset_n_trials)),
            per_asset_timeout_s=float(raw_optimization.get("per_asset_timeout_s", OptimizationConfig.per_asset_timeout_s)),
            per_asset_bound_fraction=float(raw_optimization.get("per_asset_bound_fraction", OptimizationConfig.per_asset_bound_fraction)),
            per_asset_regularization_weight=float(raw_optimization.get("per_asset_regularization_weight", OptimizationConfig.per_asset_regularization_weight)),
            per_asset_min_bars=int(raw_optimization.get("per_asset_min_bars", OptimizationConfig.per_asset_min_bars)),
            per_asset_train_bars=int(raw_optimization.get("per_asset_train_bars", OptimizationConfig.per_asset_train_bars)),
            per_asset_test_bars=int(raw_optimization.get("per_asset_test_bars", OptimizationConfig.per_asset_test_bars)),
            per_asset_step_bars=int(raw_optimization.get("per_asset_step_bars", OptimizationConfig.per_asset_step_bars)),
            per_asset_purge_bars=int(raw_optimization.get("per_asset_purge_bars", OptimizationConfig.per_asset_purge_bars)),
            per_asset_validation_drop_threshold=float(raw_optimization.get("per_asset_validation_drop_threshold", OptimizationConfig.per_asset_validation_drop_threshold)),
            per_asset_min_zone_count_gate=int(raw_optimization.get("per_asset_min_zone_count_gate", OptimizationConfig.per_asset_min_zone_count_gate)),
            per_asset_min_survival_rate_constraint=float(raw_optimization.get("per_asset_min_survival_rate_constraint", OptimizationConfig.per_asset_min_survival_rate_constraint)),
            per_asset_gate_penalty=float(raw_optimization.get("per_asset_gate_penalty", OptimizationConfig.per_asset_gate_penalty)),
            per_asset_constraint_penalty_floor=float(raw_optimization.get("per_asset_constraint_penalty_floor", OptimizationConfig.per_asset_constraint_penalty_floor)),
            per_asset_sampler=str(raw_optimization.get("per_asset_sampler", OptimizationConfig.per_asset_sampler)),
            per_asset_fold_stride=int(raw_optimization.get("per_asset_fold_stride", OptimizationConfig.per_asset_fold_stride)),
            per_asset_max_lookback=int(raw_optimization.get("per_asset_max_lookback", OptimizationConfig.per_asset_max_lookback)),
            seed=int(raw_optimization.get("seed", OptimizationConfig.seed)),
            quality_reversal_threshold_pct=float(raw_optimization.get("quality_reversal_threshold_pct", OptimizationConfig.quality_reversal_threshold_pct)),
            quality_coverage_proximity_atr=float(raw_optimization.get("quality_coverage_proximity_atr", OptimizationConfig.quality_coverage_proximity_atr)),
            quality_weights=dict(raw_optimization.get("quality_weights", {
                "survival_rate": 0.25,
                "touch_accuracy": 0.30,
                "false_breakout_rate": 0.20,
                "strength_stability": 0.10,
                "coverage": 0.15,
            })),
        )

    def resolve(
        self,
        symbol: str,
        timeframe: str,
        raw_config: dict,
        *,
        characteristics: Optional[AssetCharacteristics] = None,
    ) -> SRResolvedConfig:
        # 1. Metadata
        metadata = self._resolve_metadata(symbol, raw_config.get("asset_metadata", {}))

        # 2-5. Cascade merge
        merged = self._cascade_merge(symbol, timeframe, raw_config)
        merged.pop("_optimization_meta", None)  # metadata-only, not runtime config
        merged.pop("_profiler_meta", None)  # metadata-only, not runtime config
        merged = _normalize_kernel_param_aliases(merged)
        merged = _normalize_legacy_ensemble_method(merged)
        merged, profiler_meta, requires_sidecar_derivation = self._materialize_sidecar_fields(
            symbol,
            timeframe,
            raw_config,
            merged,
        )

        # Rule-derived config object
        rd_cfg = self._build_rule_derived_config(merged.get("rule_derived", {}))

        # 6. Rule-derived params used by kernels and lifecycle fallbacks.
        # The live path remains data-free; only config- and timeframe-based
        # defaults are allowed here.
        rd_params = self._build_live_rule_derived_params(
            timeframe=timeframe,
            metadata=metadata,
            merged=merged,
            rd_cfg=rd_cfg,
        )

        # 7. Build section configs
        # Config Migration: Move old enhancement thresholds to lifecycle
        enhancement_raw = dict(merged.get("enhancement", {}))
        
        lifecycle_raw = dict(merged.get("lifecycle", {}))
        
        # Backward compatibility migration
        if "breakout_atr_threshold" in enhancement_raw and "breakout_atr_threshold" not in lifecycle_raw:
            lifecycle_raw["breakout_atr_threshold"] = enhancement_raw.pop("breakout_atr_threshold")

        pipeline_dict = _normalize_enabled_kernels(merged.get("pipeline", {}))
        pipeline = _dict_to_frozen(PipelineConfig, pipeline_dict)
        ensemble = _dict_to_frozen(EnsembleConfig, merged.get("ensemble", {}))
        lifecycle = _dict_to_frozen(LifecycleConfig, lifecycle_raw)
        enhancement = _dict_to_frozen(EnhancementConfig, enhancement_raw)
        regime = _dict_to_frozen(RegimeConfig, merged.get("regime", {}))
        features = _dict_to_frozen(FeaturesConfig, merged.get("features", {}))

        return SRResolvedConfig(
            metadata=metadata,
            pipeline=pipeline,
            kernels=merged.get("kernels", {}),
            ensemble=ensemble,
            lifecycle=lifecycle,
            enhancement=enhancement,
            regime=regime,
            rule_derived=rd_params,
            rule_derived_config=rd_cfg,
            features=features,
            profiler_meta=profiler_meta,
            requires_sidecar_derivation=requires_sidecar_derivation,
        )

    # -- public helpers (used by sidecar daemon) ----------------------------

    def resolve_metadata(self, symbol: str, am_config: dict) -> AssetMetadata:
        """Resolve asset metadata from profiles + per-asset overrides."""
        return self._resolve_metadata(symbol, am_config)

    def cascade_merge(self, symbol: str, timeframe: str, raw_config: dict) -> dict:
        """Merge: global → per-TF → per-asset defaults → per-asset/TF."""
        return self._cascade_merge(symbol, timeframe, raw_config)

    def build_rule_derived_config(self, rd_dict: dict):
        """Build typed RuleDerivedConfig from raw dict."""
        return self._build_rule_derived_config(rd_dict)

    # -- internal helpers ---------------------------------------------------

    def _resolve_metadata(self, symbol: str, am_config: dict) -> AssetMetadata:
        """Resolve asset metadata from profiles + per-asset overrides."""
        profiles = am_config.get("profiles", _DEFAULT_PROFILES)
        per_asset = am_config.get("assets", {}).get(symbol, {})

        profile_name = per_asset.get("profile", "crypto")
        base = dict(profiles.get(profile_name, _DEFAULT_PROFILES.get("crypto", {})))

        # Apply per-asset overrides
        for k, v in per_asset.items():
            if k != "profile":
                base[k] = v

        base["profile"] = profile_name
        return AssetMetadata(**base)

    def _cascade_merge(self, symbol: str, timeframe: str, raw_config: dict) -> dict:
        """Merge: global → per-TF → per-asset defaults → per-asset/TF."""
        sr = dict(raw_config.get("sr", {}))
        per_tf = raw_config.get("per_tf", {}).get(timeframe, {})
        assets = raw_config.get("assets", {}).get(symbol, {})
        asset_defaults = assets.get("defaults", {})
        asset_tf = assets.get(timeframe, {})

        merged = copy.deepcopy(sr)
        merged = _deep_merge(merged, per_tf)
        merged = _deep_merge(merged, asset_defaults)
        merged = _deep_merge(merged, asset_tf)
        return merged

    def _materialize_sidecar_fields(
        self,
        symbol: str,
        timeframe: str,
        raw_config: dict,
        merged: dict,
    ) -> tuple[dict, Dict[str, Any], bool]:
        """Project sidecar-owned fields into the live config with safe fallbacks."""
        assets = raw_config.get("assets", {}).get(symbol, {})
        asset_tf = assets.get(timeframe, {}) if isinstance(assets, dict) else {}
        if not isinstance(asset_tf, dict):
            asset_tf = {}

        materialized = copy.deepcopy(merged)
        pipeline_cfg = dict(materialized.get("pipeline", {}))
        lifecycle_cfg = dict(materialized.get("lifecycle", {}))
        enhancement_cfg = dict(materialized.get("enhancement", {}))
        kernels_cfg = copy.deepcopy(materialized.get("kernels", {}))

        profiler_meta = asset_tf.get("_profiler_meta", {})
        if not isinstance(profiler_meta, dict):
            profiler_meta = {}
        requires_sidecar_derivation = not profiler_meta

        asset_tf_pipeline = asset_tf.get("pipeline", {}) if isinstance(asset_tf.get("pipeline", {}), dict) else {}
        asset_tf_lifecycle = asset_tf.get("lifecycle", {}) if isinstance(asset_tf.get("lifecycle", {}), dict) else {}
        asset_tf_enhancement = asset_tf.get("enhancement", {}) if isinstance(asset_tf.get("enhancement", {}), dict) else {}

        for field_name, fallback in _SIDECAR_PIPELINE_FALLBACKS.items():
            explicit_value = asset_tf_pipeline.get(field_name)
            if explicit_value is None:
                requires_sidecar_derivation = True
                explicit_value = fallback

            pipeline_cfg.setdefault(field_name, explicit_value)
            if field_name == "dedup_proximity_atr":
                lifecycle_cfg.setdefault("dedup_proximity_atr", explicit_value)
            elif field_name == "zone_half_width_atr":
                for kernel_name in _ZONE_HALF_WIDTH_KERNELS:
                    kernel_cfg = dict(kernels_cfg.get(kernel_name, {}))
                    kernel_cfg.setdefault("zone_half_width_atr", explicit_value)
                    kernels_cfg[kernel_name] = kernel_cfg

        for field_name, fallback in _SIDECAR_LIFECYCLE_FALLBACKS.items():
            explicit_value = asset_tf_lifecycle.get(field_name)
            if explicit_value is None:
                requires_sidecar_derivation = True
                explicit_value = fallback
            lifecycle_cfg.setdefault(field_name, explicit_value)

        for field_name, fallback in _SIDECAR_ENHANCEMENT_FALLBACKS.items():
            explicit_value = asset_tf_enhancement.get(field_name)
            if explicit_value is None:
                requires_sidecar_derivation = True
                explicit_value = fallback
            enhancement_cfg.setdefault(field_name, explicit_value)

        materialized["pipeline"] = pipeline_cfg
        materialized["lifecycle"] = lifecycle_cfg
        materialized["enhancement"] = enhancement_cfg
        materialized["kernels"] = kernels_cfg
        return materialized, copy.deepcopy(profiler_meta), requires_sidecar_derivation

    def _build_live_rule_derived_params(
        self,
        timeframe: str,
        metadata: AssetMetadata,
        merged: dict,
        rd_cfg: RuleDerivedConfig,
    ) -> RuleDerivedParams:
        """Build the runtime rule-derived bundle without live-data characteristics."""
        neutral = self._neutral_rule_derived()
        tf_minutes = _TIMEFRAME_MINUTES.get(timeframe, 60)
        tf_ratio = tf_minutes / 60.0

        n1 = int(_clip(
            round(rd_cfg.pivot.base_multiplier * math.sqrt(tf_ratio)),
            rd_cfg.pivot.n1_min,
            rd_cfg.pivot.n1_max,
        ))
        n2 = int(_clip(
            round(rd_cfg.pivot.n2_ratio * n1),
            rd_cfg.pivot.n2_min,
            rd_cfg.pivot.n2_max,
        ))
        confirm_bars = int(_clip(
            round(rd_cfg.breakout.base_multiplier * math.sqrt(tf_ratio)),
            rd_cfg.breakout.confirm_min,
            rd_cfg.breakout.confirm_max,
        ))

        lifecycle_cfg = merged.get("lifecycle", {})
        enhancement_cfg = merged.get("enhancement", {})
        pipeline_cfg = merged.get("pipeline", {})
        kernels_cfg = merged.get("kernels", {})

        zone_half_width = neutral.zone_half_width_atr
        for kernel_name in _ZONE_HALF_WIDTH_KERNELS:
            kernel_cfg = kernels_cfg.get(kernel_name, {})
            if isinstance(kernel_cfg, dict) and kernel_cfg.get("zone_half_width_atr") is not None:
                zone_half_width = float(kernel_cfg["zone_half_width_atr"])
                break

        false_breakout_window = lifecycle_cfg.get(
            "false_breakout_window",
            rd_cfg.breakout.false_breakout_multiplier * confirm_bars,
        )

        return RuleDerivedParams(
            n1=n1,
            n2=n2,
            fractal_period=max(2, int(rd_cfg.fractal.period_multiplier * n1)),
            fractal_buffer=neutral.fractal_buffer,
            round_interval=neutral.round_interval,
            max_zone_width_atr=neutral.max_zone_width_atr,
            max_zone_width_pct=neutral.max_zone_width_pct,
            breakout_confirm_bars=int(_coalesce(lifecycle_cfg.get("breakout_confirm_bars"), confirm_bars)),
            false_breakout_window=int(_coalesce(false_breakout_window, neutral.false_breakout_window)),
            inactivity_threshold=int(_coalesce(lifecycle_cfg.get("inactivity_threshold"), neutral.inactivity_threshold)),
            inactivity_decay=float(_coalesce(lifecycle_cfg.get("inactivity_decay"), neutral.inactivity_decay)),
            max_active_zones=int(_coalesce(lifecycle_cfg.get("max_active_zones"), neutral.max_active_zones)),
            volume_spike_threshold=float(_coalesce(enhancement_cfg.get("volume_spike_threshold"), neutral.volume_spike_threshold)),
            breakout_atr_threshold=float(_coalesce(lifecycle_cfg.get("breakout_atr_threshold"), neutral.breakout_atr_threshold)),
            touch_proximity_atr=float(_coalesce(lifecycle_cfg.get("touch_proximity_atr"), neutral.touch_proximity_atr)),
            false_breakout_recovery_bars=int(_coalesce(lifecycle_cfg.get("false_breakout_recovery_bars"), neutral.false_breakout_recovery_bars)),
            merge_threshold_pct_atr=float(_coalesce(pipeline_cfg.get("merge_threshold_pct_atr"), neutral.merge_threshold_pct_atr)),
            dedup_proximity_atr=float(_coalesce(lifecycle_cfg.get("dedup_proximity_atr"), neutral.dedup_proximity_atr)),
            zone_half_width_atr=zone_half_width,
            vp_lookback_hours=list(metadata.session_lookback_hours),
        )

    def _build_rule_derived_config(self, rd_dict: dict) -> RuleDerivedConfig:
        """Build typed RuleDerivedConfig from raw dict, using defaults for missing fields."""
        if not rd_dict:
            return RuleDerivedConfig()

        from app.sr.config_schema import (
            PivotFormulaConfig,
            FractalFormulaConfig,
            BreakoutFormulaConfig,
            ZoneWidthFormulaConfig,
            InactivityFormulaConfig,
            MaxZonesFormulaConfig,
            VolumeSpikeFormulaConfig,
            HurstFallbackConfig,
            WickAdaptationConfig,
        )

        return RuleDerivedConfig(
            pivot=_dict_to_frozen(PivotFormulaConfig, rd_dict.get("pivot", {})),
            fractal=_dict_to_frozen(FractalFormulaConfig, rd_dict.get("fractal", {})),
            breakout=_dict_to_frozen(BreakoutFormulaConfig, rd_dict.get("breakout", {})),
            zone_width=_dict_to_frozen(ZoneWidthFormulaConfig, rd_dict.get("zone_width", {})),
            inactivity=_dict_to_frozen(InactivityFormulaConfig, rd_dict.get("inactivity", {})),
            max_zones=_dict_to_frozen(MaxZonesFormulaConfig, rd_dict.get("max_zones", {})),
            volume_spike=_dict_to_frozen(VolumeSpikeFormulaConfig, rd_dict.get("volume_spike", {})),
            hurst_fallback=_dict_to_frozen(HurstFallbackConfig, rd_dict.get("hurst_fallback", {})),
            wick_adaptation=_dict_to_frozen(WickAdaptationConfig, rd_dict.get("wick_adaptation", {})),
        )

    def _neutral_rule_derived(self) -> RuleDerivedParams:
        """Provide neutral rule-derived defaults when no market data is available.

        Assumes 1h timeframe for temporal parameters.
        """
        return RuleDerivedParams(
            n1=8, n2=6,
            fractal_period=16, fractal_buffer=0.0,
            round_interval=10.0,
            max_zone_width_atr=2.0, max_zone_width_pct=3.0,
            breakout_confirm_bars=3, false_breakout_window=6,
            inactivity_threshold=168, max_active_zones=10,
            inactivity_decay=0.008,
            volume_spike_threshold=1.5,
            breakout_atr_threshold=0.3,
            touch_proximity_atr=0.1,
            false_breakout_recovery_bars=6,
            merge_threshold_pct_atr=0.25,
            dedup_proximity_atr=0.5,
            zone_half_width_atr=0.1,
            vp_lookback_hours=[24, 168, 720],
        )
