"""Configuration objects for RegimeV2 phase 1."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class DataQualityConfig:
    required_fields: tuple[str, ...] = ("open", "high", "low", "close", "volume")
    min_bars: int = 120
    max_missing_ratio: float = 0.02
    extreme_return_z: float = 8.0


@dataclass(frozen=True)
class TrendConfig:
    fast_ema: int = 20
    slow_ema: int = 50
    efficiency_lookback: int = 24
    persistence_lookback: int = 12
    slope_atr_scale: float = 3.0
    ema_score_weight: float = 0.50
    efficiency_score_weight: float = 0.35
    persistence_score_weight: float = 0.15
    confidence_strength_weight: float = 0.60
    confidence_persistence_weight: float = 0.40
    direction_deadzone: float = 0.12


@dataclass(frozen=True)
class VolatilityConfig:
    realized_window: int = 24
    percentile_window: int = 500
    compression_window: int = 120
    shock_z: float = 3.0
    realized_weight: float = 0.65
    atr_weight: float = 0.35
    compression_low_quantile: float = 0.10
    compression_high_quantile: float = 0.90
    shock_state_threshold: float = 0.80
    expanding_percentile_threshold: float = 75.0
    compressed_threshold: float = 0.70
    quiet_percentile_threshold: float = 30.0


@dataclass(frozen=True)
class MeanReversionConfig:
    center_window: int = 40
    band_window: int = 40
    chop_window: int = 24
    z_clip: float = 4.0
    chop_ci_center: float = 0.45
    chop_ci_width: float = 0.35
    range_quality_chop_weight: float = 0.55
    range_quality_cross_weight: float = 0.45
    chop_risk_chop_weight: float = 0.70
    chop_risk_abs_ret_weight: float = 0.30
    chop_risk_abs_ret_scale: float = 3.0


@dataclass(frozen=True)
class BreakConfig:
    range_window: int = 24
    breakout_window: int = 50
    shock_z: float = 3.0
    confirmation_volume_z: float = 1.0
    breakout_magnitude_scale: float = 3.0
    displacement_volume_base: float = 0.60
    displacement_volume_weight: float = 0.40
    edge_pressure_center: float = 0.55
    edge_pressure_width: float = 0.35
    setup_quiet_base: float = 0.60
    setup_quiet_weight: float = 0.40
    retest_distance_scale: float = 0.18
    retest_boundary_buffer: float = 0.005
    retest_quiet_base: float = 0.70
    retest_quiet_weight: float = 0.30
    false_breakout_displacement_weight: float = 0.50
    false_breakout_rejection_weight: float = 0.30
    false_breakout_low_ret_weight: float = 0.20
    false_breakout_low_ret_z_max: float = 1.0
    structural_break_ret_weight: float = 0.45
    structural_break_range_weight: float = 0.35
    structural_break_displacement_weight: float = 0.20
    breakout_quality_setup_weight: float = 0.75
    breakout_quality_retest_weight: float = 0.85
    breakout_direction_min_quality: float = 0.05


@dataclass(frozen=True)
class MarketContextConfig:
    alignment_column: str = "eng_regime_alignment_score"
    breadth_column: str = "eng_market_cap_breadth"
    regime_state_column: str = "eng_cross_asset_regime_state"
    liquidity_columns: tuple[str, ...] = ("spread_bps", "bid_ask_imbalance", "depth_ratio")
    breadth_tanh_scale: float = 10.0
    alignment_weight: float = 0.65
    breadth_weight: float = 0.35
    spread_stress_divisor: float = 20.0
    spread_stress_weight: float = 0.45
    imbalance_stress_weight: float = 0.25
    depth_stress_divisor: float = 2.0
    depth_stress_weight: float = 0.30


@dataclass(frozen=True)
class FusionConfig:
    min_confidence: float = 0.05
    high_confidence_uncertainty_cap: float = 0.55
    trend_threshold: float = 0.48
    mr_threshold: float = 0.55
    chop_threshold: float = 0.65
    break_threshold: float = 0.65
    shock_threshold: float = 0.70
    trend_chop_discount_weight: float = 0.50
    trend_chop_discount_max: float = 0.45
    conflict_shock_weight: float = 0.75
    conflict_liquidity_weight: float = 0.50
    confidence_conflict_penalty: float = 0.55
    uncertainty_conflict_weight: float = 0.35
    warmup_confidence_multiplier: float = 0.25
    transition_breakout_min: float = 0.45
    trend_chop_max: float = 0.60
    mr_context_range_min: float = 0.30
    mr_context_compression_min: float = 0.70
    mr_break_risk_max: float = 0.60
    compressed_label_threshold: float = 0.72


@dataclass(frozen=True)
class PolicyConfig:
    min_confidence: float = 0.30
    high_uncertainty_no_trade: float = 0.82
    no_trade_shock_threshold: float = 0.85
    no_trade_liquidity_threshold: float = 0.85
    trend_min_strength: float = 0.48
    trend_max_chop: float = 0.55
    uncertainty_soft_penalty_weight: float = 0.35
    trend_persistence_base: float = 0.70
    trend_persistence_weight: float = 0.30
    breakout_min_quality: float = 0.58
    breakout_max_false_break: float = 0.58
    breakout_setup_min: float = 0.58
    breakout_setup_max_break_risk: float = 0.45
    breakout_setup_max_shock: float = 0.55
    displacement_breakout_max_shock: float = 0.80
    retest_breakout_min: float = 0.35
    retest_breakout_max_break_risk: float = 0.65
    mr_min_score: float = 0.58
    mr_max_break_risk: float = 0.55
    mr_context_compression_weight: float = 0.75
    mr_context_min: float = 0.45
    scalping_max_shock: float = 0.65
    scalping_max_liquidity: float = 0.65
    scalping_context_base: float = 0.55
    scalping_context_weight: float = 0.45
    countertrend_min_range: float = 0.70
    countertrend_max_trend_strength: float = 0.45
    countertrend_max_break_risk: float = 0.45
    base_holding_period: int = 12
    playbook_score_floor_min: float = 0.20
    playbook_score_floor_max: float = 0.40
    playbook_score_floor_confidence_mult: float = 0.80
    threshold_width: float = 0.20
    position_scale_liquidity_penalty_weight: float = 0.80
    position_scale_risk_penalty_weight: float = 0.65
    position_scale_break_risk_threshold: float = 0.70
    position_scale_breakout_quality_threshold: float = 0.65
    position_scale_break_risk_multiplier: float = 0.50
    stop_base: float = 1.0
    stop_shock_weight: float = 0.75
    stop_break_weight: float = 0.35
    stop_expanding_bonus: float = 0.25
    stop_min: float = 0.7
    stop_max: float = 2.5
    target_base: float = 1.0
    target_trend_weight: float = 0.45
    target_breakout_weight: float = 0.35
    target_chop_threshold: float = 0.70
    target_chop_multiplier: float = 0.75
    target_min: float = 0.6
    target_max: float = 2.2
    holding_period_trend_strength_threshold: float = 0.65
    holding_period_trend_chop_max: float = 0.45
    holding_period_trend_multiplier: float = 1.5
    holding_period_mr_threshold: float = 0.65
    holding_period_shock_threshold: float = 0.65
    holding_period_reduction_multiplier: float = 0.6


@dataclass(frozen=True)
class RegimeV2Config:
    data_quality: DataQualityConfig = DataQualityConfig()
    trend: TrendConfig = TrendConfig()
    volatility: VolatilityConfig = VolatilityConfig()
    mean_reversion: MeanReversionConfig = MeanReversionConfig()
    breaks: BreakConfig = BreakConfig()
    market_context: MarketContextConfig = MarketContextConfig()
    fusion: FusionConfig = FusionConfig()
    policy: PolicyConfig = PolicyConfig()


_BARS_PER_HOUR: dict[str, float] = {
    "1m": 60.0,
    "3m": 20.0,
    "5m": 12.0,
    "15m": 4.0,
    "30m": 2.0,
    "1h": 1.0,
    "2h": 0.5,
    "4h": 0.25,
    "1d": 1.0 / 24.0,
}


def scale_bars(base_1h: int, timeframe: str, *, floor: int = 2) -> int:
    """Scale a 1h bar-count window to another timeframe."""
    ratio = _BARS_PER_HOUR.get(timeframe, 1.0)
    return max(int(round(base_1h * ratio)), floor)


def timeframe_scaled_config(
    timeframe: str = "1h",
    overrides: dict[str, Any] | None = None,
) -> RegimeV2Config:
    """Build config with bar-count windows scaled to the requested timeframe.

    Overrides use dotted keys such as ``trend.fast_ema`` or ``policy.min_confidence``.
    """
    cfg = RegimeV2Config(
        data_quality=replace(
            RegimeV2Config.data_quality,
            min_bars=scale_bars(RegimeV2Config.data_quality.min_bars, timeframe, floor=40),
        ),
        trend=replace(
            RegimeV2Config.trend,
            fast_ema=scale_bars(RegimeV2Config.trend.fast_ema, timeframe, floor=5),
            slow_ema=scale_bars(RegimeV2Config.trend.slow_ema, timeframe, floor=10),
            efficiency_lookback=scale_bars(RegimeV2Config.trend.efficiency_lookback, timeframe, floor=5),
            persistence_lookback=scale_bars(RegimeV2Config.trend.persistence_lookback, timeframe, floor=4),
        ),
        volatility=replace(
            RegimeV2Config.volatility,
            realized_window=scale_bars(RegimeV2Config.volatility.realized_window, timeframe, floor=5),
            percentile_window=scale_bars(RegimeV2Config.volatility.percentile_window, timeframe, floor=100),
            compression_window=scale_bars(RegimeV2Config.volatility.compression_window, timeframe, floor=30),
        ),
        mean_reversion=replace(
            RegimeV2Config.mean_reversion,
            center_window=scale_bars(RegimeV2Config.mean_reversion.center_window, timeframe, floor=10),
            band_window=scale_bars(RegimeV2Config.mean_reversion.band_window, timeframe, floor=10),
            chop_window=scale_bars(RegimeV2Config.mean_reversion.chop_window, timeframe, floor=5),
        ),
        breaks=replace(
            RegimeV2Config.breaks,
            range_window=scale_bars(RegimeV2Config.breaks.range_window, timeframe, floor=5),
            breakout_window=scale_bars(RegimeV2Config.breaks.breakout_window, timeframe, floor=10),
        ),
    )
    return apply_overrides(cfg, overrides or {})


def apply_overrides(cfg: RegimeV2Config, overrides: dict[str, Any]) -> RegimeV2Config:
    """Apply dotted-key dataclass overrides."""
    if not overrides:
        return cfg

    sections = {
        "data_quality": cfg.data_quality,
        "trend": cfg.trend,
        "volatility": cfg.volatility,
        "mean_reversion": cfg.mean_reversion,
        "breaks": cfg.breaks,
        "market_context": cfg.market_context,
        "fusion": cfg.fusion,
        "policy": cfg.policy,
    }
    patched: dict[str, Any] = dict(sections)
    for key, value in overrides.items():
        if "." not in key:
            continue
        section, field_name = key.split(".", 1)
        if section not in patched:
            continue
        section_obj = patched[section]
        if hasattr(section_obj, field_name):
            patched[section] = replace(section_obj, **{field_name: value})

    return RegimeV2Config(**patched)


__all__ = [
    "DataQualityConfig",
    "TrendConfig",
    "VolatilityConfig",
    "MeanReversionConfig",
    "BreakConfig",
    "MarketContextConfig",
    "FusionConfig",
    "PolicyConfig",
    "RegimeV2Config",
    "scale_bars",
    "timeframe_scaled_config",
]
