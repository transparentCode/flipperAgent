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


@dataclass(frozen=True)
class VolatilityConfig:
    realized_window: int = 24
    percentile_window: int = 500
    compression_window: int = 120
    shock_z: float = 3.0


@dataclass(frozen=True)
class MeanReversionConfig:
    center_window: int = 40
    band_window: int = 40
    chop_window: int = 24
    z_clip: float = 4.0


@dataclass(frozen=True)
class BreakConfig:
    range_window: int = 24
    breakout_window: int = 50
    shock_z: float = 3.0
    confirmation_volume_z: float = 1.0


@dataclass(frozen=True)
class MarketContextConfig:
    alignment_column: str = "eng_regime_alignment_score"
    breadth_column: str = "eng_market_cap_breadth"
    regime_state_column: str = "eng_cross_asset_regime_state"
    liquidity_columns: tuple[str, ...] = ("spread_bps", "bid_ask_imbalance", "depth_ratio")


@dataclass(frozen=True)
class FusionConfig:
    min_confidence: float = 0.05
    high_confidence_uncertainty_cap: float = 0.55
    trend_threshold: float = 0.48
    mr_threshold: float = 0.55
    chop_threshold: float = 0.65
    break_threshold: float = 0.65
    shock_threshold: float = 0.70


@dataclass(frozen=True)
class PolicyConfig:
    min_confidence: float = 0.30
    high_uncertainty_no_trade: float = 0.82
    trend_min_strength: float = 0.48
    trend_max_chop: float = 0.55
    breakout_min_quality: float = 0.58
    breakout_max_false_break: float = 0.58
    mr_min_score: float = 0.58
    mr_max_break_risk: float = 0.55
    scalping_max_shock: float = 0.65
    countertrend_min_range: float = 0.70
    base_holding_period: int = 12


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
