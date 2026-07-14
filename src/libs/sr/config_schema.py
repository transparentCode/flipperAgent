"""
S/R v2 Config Schema
====================
Typed config dataclasses for the v2 YAML schema.

All config values flow through the 4-tier cascade
(asset-metadata → global → per-TF → per-asset) resolved
by ``SRConfigResolver``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.sr.models import AssetMetadata, RuleDerivedParams


# ---------------------------------------------------------------------------
# Section configs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PipelineConfig:
    """Top-level pipeline toggles."""
    enabled_kernels: List[str] = field(default_factory=lambda: ["pivot_hl", "volume_poc"])
    atr_period: int = 14
    avg_volume_window: int = 20
    merge_threshold_pct_atr: float = 0.25  # Spatial deduplication threshold
    min_emit_strength: float = 0.0         # Gate: reject scored levels below this strength (0=disabled)
    max_new_zones_per_bar: int = 0         # Gate: keep only top-N strongest per bar (0=unlimited)
    min_zone_quality: float = 0.0          # Gate: reject scored levels below this ZQS (0=disabled)
    candidate_dedup_staleness_bars: int = 5   # Cross-bar dedup: ignore re-detections within N bars
    candidate_dedup_quantize_atr: float = 0.25  # Cross-bar dedup: price-quantization bucket width (ATR fraction)


@dataclass(frozen=True)
class PivotKernelConfig:
    min_bars: int = 14
    historical_depth: int = 500
    smoothing_period: int = 3
    zone_half_width_atr: float = 0.1
    vol_factor_weight: float = 0.5
    dominance_weight: float = 0.5


@dataclass(frozen=True)
class VolumePOCKernelConfig:
    min_bars: int = 10
    num_bins: int = 50
    value_area_pct: float = 0.70
    poc_strength: float = 0.9
    vah_val_strength: float = 0.7
    hvn_strength: float = 0.6
    max_hvn_count: int = 3
    hvn_prominence: float = 0.2
    zone_half_width_atr: float = 0.15
    hvn_min_distance_atr: float = 0.3
    hvn_peak_distance_bins: int = 3


@dataclass(frozen=True)
class AnchoredVWAPKernelConfig:
    min_bars: int = 20
    anchor_type: str = "hybrid"
    volume_spike_multiplier: float = 2.0


@dataclass(frozen=True)
class TPOValueAreaKernelConfig:
    min_bars: int = 20
    tpo_window_bars: int = 120
    tpo_value_area_pct: float = 0.68


@dataclass(frozen=True)
class SessionGapKernelConfig:
    min_bars: int = 20
    gap_min_atr: float = 0.5
    fill_level_fractions: List[float] = field(default_factory=lambda: [0.5])
    max_age_bars: int = 500
    gap_origin_strength: float = 0.7
    gap_dest_strength: float = 0.7
    fill_level_strength: float = 0.6
    max_gap_atr_cap: float = 2.0
    session_boundary_multiplier: float = 1.5
    session_boundary_baseline_bars: int = 20

@dataclass(frozen=True)
class FairValueGapKernelConfig:
    min_bars: int = 20
    gap_min_atr: float = 0.5
    fill_threshold: float = 0.5
    max_age_bars: int = 200
    validity_lookback_bars: int = 5
    fvg_strength: float = 0.75
    max_gap_atr_cap: float = 2.0
    filled_penalty_multiplier: float = 0.5

@dataclass(frozen=True)
class OrderBlockKernelConfig:
    min_bars: int = 20
    displacement_atr: float = 1.5
    imbalance_ratio: float = 0.7
    max_age_bars: int = 200
    validity_lookback_bars: int = 5
    ob_strength: float = 0.8

@dataclass(frozen=True)
class RoundNumberKernelConfig:
    min_bars: int = 14
    atr_snap_factor: float = 0.5
    max_levels: int = 20
    strength_decay: float = 0.05
    base_confidence: float = 0.5
    score_skip_threshold: float = 0.05
    pip_intervals: Dict[str, float] = field(default_factory=lambda: {"micro": 0.01, "minor": 1.0, "major": 10.0})
    pip_thresholds: Dict[str, float] = field(default_factory=lambda: {"micro_max": 2.0, "minor_max": 200.0})

@dataclass(frozen=True)
class RegressionBandKernelConfig:
    min_bars: int = 30
    band_width_sigma: float = 2.0
    emit_center: bool = False
    band_strength: float = 0.8
    center_strength: float = 0.6
    zone_half_width_atr: float = 0.1

@dataclass(frozen=True)
class FractalChannelKernelConfig:
    min_bars: int = 30
    channel_lookback: int = 32
    boundary_buffer_atr: float = 0.1
    use_rule_derived_buffer: bool = False
    pivot_method: str = "fractal"
    mode: str = "geometric"
    emit_midline: bool = False
    channel_strength: float = 0.85
    midline_strength_factor: float = 0.6

@dataclass(frozen=True)
class LiquiditySweepKernelConfig:
    min_bars: int = 20
    sweep_lookback: int = 50
    max_pierce_atr: float = 1.0
    max_age_bars: int = 200
    sweep_strength: float = 0.8
    zone_half_width_atr: float = 0.1


@dataclass(frozen=True)
class EnsembleConfig:
    method: str = "weighted_average"
    structural_vs_micro_ratio: float = 0.5
    kernel_weights: Dict[str, float] = field(default_factory=dict)
    structural_kernels: List[str] = field(default_factory=lambda: ["pivot_hl", "fractal_channel", "regression_band", "anchored_vwap"])
    micro_kernels: List[str] = field(default_factory=lambda: ["volume_poc", "order_block", "fair_value_gap", "round_number", "session_gap", "liquidity_sweep", "tpo_value_area"])
    confidence: Dict[str, float] = field(default_factory=dict)
    confidence_weighted: Dict[str, float] = field(default_factory=dict)
    regime_conditional: Dict[str, float] = field(default_factory=dict)
    meta_learned: Dict[str, float] = field(default_factory=dict)
    contributing_proximity_atr: float = 0.5
    # Zone Quality Score (ZQS) weights
    zone_quality: Dict[str, float] = field(default_factory=lambda: {
        "strength_weight": 0.35,
        "confidence_weight": 0.30,
        "volume_weight": 0.20,
        "width_penalty_weight": 0.15,
        "width_decay_alpha": 3.0,
    })


@dataclass(frozen=True)
class LifecycleConfig:
    age_lambda: float = 0.002
    inactivity_decay: float = 0.8
    min_strength: float = 0.3
    breakout_atr_threshold: Optional[float] = None   # rule-derived from wick_adaptation
    touch_proximity_atr: Optional[float] = None       # rule-derived from wick_adaptation
    false_breakout_recovery_bars: Optional[int] = None # rule-derived from wick_adaptation
    stale_distance_atr: float = 3.0
    max_age_bars: int = 200
    dedup_proximity_atr: float = 0.5
    auto_promote_kernel_agreement: int = 2
    min_touches_to_confirm: int = 1
    flip_require_retest: bool = True
    false_breakout_strength_boost: float = 1.15
    test_held_strength_boost: float = 1.1
    merge_strength_mode: str = "max"
    min_zones_per_kernel: int = 1
    # Rule-derived fields filled by resolver:
    breakout_confirm_bars: Optional[int] = None
    false_breakout_window: Optional[int] = None
    inactivity_threshold: Optional[int] = None
    max_active_zones: Optional[int] = None


@dataclass(frozen=True)
class EnhancementConfig:
    stop_hunt_pierce_atr: float = 0.2
    volume_spike_threshold: Optional[float] = None  # rule-derived


@dataclass(frozen=True)
class FeaturesConfig:
    """Feature builder/context knobs consumed at runtime."""
    touch_proximity_atr: float = 0.5
    cluster_density_proximity_atr: float = 1.0
    kernel_agreement_proximity_atr: float = 0.5
    breakout_proximity_atr: float = 0.3
    volume_trend_proximity_atr: float = 0.5
    false_breakout_threshold_atr: float = 0.3
    false_breakout_window_bars: int = 5
    volume_trend_lookback_hours: Optional[float] = None
    false_breakout_lookback_hours: Optional[float] = None
    regime_alignment: Dict[str, float] = field(
        default_factory=lambda: {
            "trending_resistance": -0.5,
            "trending_support": 0.5,
            "ranging": 0.7,
            "volatile": 0.0,
        }
    )
    volume_mean_window: int = 20
    volume_kurtosis_window: int = 200


@dataclass(frozen=True)
class RegimeConfig:
    enabled: bool = False
    min_confidence: float = 0.5
    max_entropy: float = 1.2
    stability_window_bars: int = 50
    confidence_ema_alpha: float = 0.2
    fallback_state: Optional[str] = None
    fallback_weights: Dict[str, float] = field(
        default_factory=lambda: {"trending": 1.0, "ranging": 1.0, "volatile": 1.0}
    )
    weights: Dict[str, float] = field(
        default_factory=lambda: {"trending": 1.0, "ranging": 1.0, "volatile": 1.0}
    )


@dataclass(frozen=True)
class OptimizationParameterConfig:
    """Typed bounds for a single optimizer parameter."""

    low: Optional[float] = None
    high: Optional[float] = None
    kind: str = "float"
    enabled: bool = True
    metadata_gate: Optional[str] = None


@dataclass(frozen=True)
class OptimizationConfig:
    """Typed optimizer defaults resolved from ``sr.optimization``."""

    # Stage 1 (universe-wide)
    n_trials: int = 50
    timeout_s: float = 3600.0
    tier6_weight: float = 0.10
    stage1_eval_bars: int = 300
    parameters: Dict[str, OptimizationParameterConfig] = field(default_factory=dict)

    # Stage 2 (per-asset)
    per_asset_n_trials: int = 30
    per_asset_timeout_s: float = 600.0
    per_asset_bound_fraction: float = 0.60
    per_asset_regularization_weight: float = 0.05
    per_asset_min_bars: int = 500
    per_asset_train_bars: int = 300
    per_asset_test_bars: int = 100
    per_asset_step_bars: int = 100
    per_asset_purge_bars: int = 10
    per_asset_validation_drop_threshold: float = 0.15
    per_asset_min_zone_count_gate: int = 3
    per_asset_min_survival_rate_constraint: float = 0.20
    per_asset_gate_penalty: float = 0.5
    per_asset_constraint_penalty_floor: float = 0.5
    per_asset_sampler: str = "tpe"
    per_asset_fold_stride: int = 3
    per_asset_max_lookback: int = 2000
    seed: int = 42

    # Quality evaluator settings
    quality_reversal_threshold_pct: float = 0.015
    quality_coverage_proximity_atr: float = 0.3
    quality_weights: Dict[str, float] = field(default_factory=lambda: {
        "survival_rate": 0.25,
        "touch_accuracy": 0.30,
        "false_breakout_rate": 0.20,
        "strength_stability": 0.10,
        "coverage": 0.15,
    })


# ---------------------------------------------------------------------------
# Rule-derived formula coefficients (§2L)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PivotFormulaConfig:
    base_multiplier: int = 8
    n1_min: int = 5
    n1_max: int = 20
    n2_ratio: float = 0.7
    n2_min: int = 4
    n2_max: int = 15


@dataclass(frozen=True)
class FractalFormulaConfig:
    period_multiplier: int = 2
    buffer_atr_fraction: float = 0.1


@dataclass(frozen=True)
class BreakoutFormulaConfig:
    base_multiplier: int = 3
    confirm_min: int = 2
    confirm_max: int = 8
    false_breakout_multiplier: int = 2


@dataclass(frozen=True)
class ZoneWidthFormulaConfig:
    base_atr: float = 1.5
    hurst_sensitivity: float = 0.5
    atr_min: float = 1.0
    atr_max: float = 4.0
    pct_multiplier: float = 2.0
    pct_min: float = 1.0
    pct_max: float = 5.0


@dataclass(frozen=True)
class InactivityFormulaConfig:
    """Formula coefficients for timeframe-adaptive inactivity decay.

    All derivations use ``tf_minutes`` from ``AssetCharacteristics`` so the
    physics of zone decay are timeframe-invariant.

    Formulas:
      inactivity_threshold = base_inactivity_hours × (60 / tf_minutes)
      inactivity_decay     = 1 - (1 - base_decay_per_hour) ^ (tf_minutes / 60)
      age_lambda           = base_age_lambda_per_hour × (tf_minutes / 60)

    The base values represent per-hour rates:
      base_inactivity_hours: hours before inactivity decay activates (default 72h = 3 days)
      base_decay_per_hour:   hourly strength decay once inactive (default 0.008 → ~50% after 3 days)
      base_age_lambda_per_hour: hourly age decay (default 0.002 → neutral)
    """
    base_inactivity_hours: float = 168.0   # 7 days before inactivity kicks in
    base_decay_per_hour: float = 0.008     # per-hour decay rate → per-bar via compounding
    min_inactivity_bars: int = 10          # floor: never trigger inactivity below this
    max_inactivity_bars: int = 1000        # ceiling: cap for very low timeframes


@dataclass(frozen=True)
class MaxZonesFormulaConfig:
    base_multiplier: int = 10
    min: int = 5
    max: int = 30


@dataclass(frozen=True)
class VolumeSpikeFormulaConfig:
    kurtosis_divisor: int = 10
    floor: float = 1.3
    ceiling: float = 2.5


@dataclass(frozen=True)
class HurstFallbackConfig:
    fallback_value: float = 0.5
    min_confidence: float = 0.6


@dataclass(frozen=True)
class WickAdaptationConfig:
    """Formula coefficients for wick-adaptive lifecycle params.

    Formulas (all use config coefficients, no magic numbers):
      breakout_atr = base_breakout + breakout_scaling * max(0, wick_ratio - neutral_wick)
      touch_prox   = base_touch   + touch_scaling   * max(0, wick_ratio - neutral_wick)
      recovery     = base_recovery + round(recovery_scaling * max(0, wick_ratio - neutral_wick))
    """
    neutral_wick: float = 1.0           # wick_body_ratio at which no adaptation occurs
    base_breakout_atr: float = 0.3      # breakout_atr_threshold when wick = neutral
    breakout_scaling: float = 0.3       # increase per unit wick above neutral
    base_touch_proximity_atr: float = 0.1
    touch_scaling: float = 0.15
    base_recovery_bars: int = 6
    recovery_scaling: float = 4.0       # additional bars per unit wick above neutral


@dataclass(frozen=True)
class RuleDerivedConfig:
    """All formula coefficients — the knobs on derivation formulas."""
    pivot: PivotFormulaConfig = field(default_factory=PivotFormulaConfig)
    fractal: FractalFormulaConfig = field(default_factory=FractalFormulaConfig)
    breakout: BreakoutFormulaConfig = field(default_factory=BreakoutFormulaConfig)
    zone_width: ZoneWidthFormulaConfig = field(default_factory=ZoneWidthFormulaConfig)
    inactivity: InactivityFormulaConfig = field(default_factory=InactivityFormulaConfig)
    max_zones: MaxZonesFormulaConfig = field(default_factory=MaxZonesFormulaConfig)
    volume_spike: VolumeSpikeFormulaConfig = field(default_factory=VolumeSpikeFormulaConfig)
    hurst_fallback: HurstFallbackConfig = field(default_factory=HurstFallbackConfig)
    wick_adaptation: WickAdaptationConfig = field(default_factory=WickAdaptationConfig)


# ---------------------------------------------------------------------------
# Resolved config (output of SRConfigResolver)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KernelResolvedConfig:
    """Config resolved for a specific kernel invocation."""
    kernel_name: str
    params: Dict[str, Any]
    metadata: AssetMetadata


@dataclass(frozen=True)
class SRResolvedConfig:
    """
    Fully resolved configuration for a (symbol, timeframe) pair.

    Contains NO hardcoded values — everything came from the cascade
    or from rule-derived formulas with configurable coefficients.
    """
    metadata: AssetMetadata
    pipeline: PipelineConfig
    kernels: Dict[str, Dict[str, Any]]
    ensemble: EnsembleConfig
    lifecycle: LifecycleConfig
    enhancement: EnhancementConfig
    regime: RegimeConfig
    rule_derived: RuleDerivedParams
    rule_derived_config: RuleDerivedConfig
    features: FeaturesConfig = field(default_factory=FeaturesConfig)
    profiler_meta: Dict[str, Any] = field(default_factory=dict)
    requires_sidecar_derivation: bool = False
