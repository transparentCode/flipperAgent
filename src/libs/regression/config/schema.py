from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class OptimizationTier(enum.Enum):
    GLOBAL = "global"
    PER_TF = "per_tf"
    PER_ASSET_CLASS = "per_asset_class"
    PER_ASSET = "per_asset"


class VolumeProfile(enum.Enum):
    CONTINUOUS = "continuous"  # crypto — 24/7, real volume
    SESSION = "session"  # stocks — gapped sessions, real volume
    PROXY = "proxy"  # fx — tick-count proxy, unreliable


from app.common.config.schema import PluginConfig  # noqa: E402 — canonical location


# ── Tier 1: Global Defaults ──


@dataclass
class GlobalConfig:
    """Tier 1: applies to all assets and timeframes unless overridden."""

    features: List[PluginConfig] = field(
        default_factory=lambda: [
            PluginConfig(name="log_price"),
            PluginConfig(name="volume_weighted"),
        ]
    )
    methods: Dict[str, PluginConfig] = field(
        default_factory=lambda: {
            "theil_sen": PluginConfig(name="theil_sen", weight=1.0),
            "vwr": PluginConfig(name="vwr", weight=1.0),
        }
    )
    ensemble: PluginConfig = field(
        default_factory=lambda: PluginConfig(name="simple_weighted")
    )
    uncertainty: PluginConfig = field(
        default_factory=lambda: PluginConfig(
            name="percentile_bands", params={"mad_scale_factor": 1.4826}
        )
    )

    # ATR fractions — all thresholds are ATR-normalized
    atr_period: int = 14
    trend_atr_fraction: float = 0.10
    spread_atr_fraction: float = 0.15
    momentum_atr_fraction: float = 0.10
    neutral_slope_atr_fraction: float = 0.04
    band_multiplier: float = 2.0

    # Window bounds (for clamping runtime overrides)
    min_window: int = 15
    max_window: int = 300
    default_window_size: int = 100


# ── Tier 2: Per-Timeframe Defaults ──


@dataclass
class TimeframeConfig:
    """Tier 2: per-timeframe overrides. None fields inherit from global."""

    window_size: Optional[int] = None
    trend_atr_fraction: Optional[float] = None
    spread_atr_fraction: Optional[float] = None
    momentum_atr_fraction: Optional[float] = None
    neutral_slope_atr_fraction: Optional[float] = None
    band_multiplier: Optional[float] = None
    slope_acceleration_alpha: Optional[float] = None

    features: Optional[List[PluginConfig]] = None
    methods: Optional[Dict[str, PluginConfig]] = None
    ensemble: Optional[PluginConfig] = None
    uncertainty: Optional[PluginConfig] = None


# ── Tier 3: Per-Asset-Class Overrides ──


@dataclass
class AssetClassConfig:
    """Tier 3: per-asset-class overrides (crypto, stock, fx)."""

    volume_profile: VolumeProfile = VolumeProfile.CONTINUOUS
    features: Optional[List[PluginConfig]] = None
    methods: Optional[Dict[str, PluginConfig]] = None
    ensemble: Optional[PluginConfig] = None

    # Session handling
    session_gap_handling: bool = False  # True for stocks
    low_liquidity_window_handling: bool = False  # True for fx


# ── Tier 4: Per-Asset Overrides ──


@dataclass
class AssetTimeframeConfig:
    """Tier 4b: per-asset-per-timeframe overrides."""

    window_size: Optional[int] = None
    trend_atr_fraction: Optional[float] = None
    spread_atr_fraction: Optional[float] = None
    momentum_atr_fraction: Optional[float] = None
    neutral_slope_atr_fraction: Optional[float] = None
    band_multiplier: Optional[float] = None
    slope_acceleration_alpha: Optional[float] = None
    methods: Optional[Dict[str, PluginConfig]] = None
    ensemble: Optional[PluginConfig] = None


@dataclass
class AssetConfig:
    """Tier 4: per-asset overrides."""

    asset_class: str = "crypto"
    mtf_enabled: bool = False
    mtf_timeframes: List[str] = field(default_factory=lambda: ["1h"])
    timeframes: Dict[str, AssetTimeframeConfig] = field(default_factory=dict)

    # Any per-asset global overrides
    window_size: Optional[int] = None
    trend_atr_fraction: Optional[float] = None
    spread_atr_fraction: Optional[float] = None
    momentum_atr_fraction: Optional[float] = None
    neutral_slope_atr_fraction: Optional[float] = None
    band_multiplier: Optional[float] = None
    methods: Optional[Dict[str, PluginConfig]] = None
    ensemble: Optional[PluginConfig] = None


# ── Orchestrator Config ──


@dataclass
class OrchestratorConfig:
    """Top-level config: wraps all tiers."""

    # MTF cascade settings (for assets that have mtf_enabled=True)
    mtf_timeframes: List[str] = field(
        default_factory=lambda: ["4h", "1h", "30m"]
    )
    tf_weights: Dict[str, float] = field(
        default_factory=lambda: {"4h": 0.5, "1h": 0.3, "30m": 0.2}
    )
    regime_context_enabled: bool = True
    regime_window_override: bool = True  # allow regime.suggested_window
    regime_window_defaults: Dict[str, int] = field(
        default_factory=lambda: {
            "CLEAN_TREND": 150,
            "VOLATILE_TREND": 60,
            "CHOPPY": 30,
            "QUIET_MR": 100,
        }
    )

    # 4 tiers
    global_config: GlobalConfig = field(default_factory=GlobalConfig)
    timeframes: Dict[str, TimeframeConfig] = field(default_factory=dict)
    asset_classes: Dict[str, AssetClassConfig] = field(default_factory=dict)
    assets: Dict[str, AssetConfig] = field(default_factory=dict)

    # Optimization metadata — declares which params belong to which search tier
    optimization: Dict[str, List[str]] = field(
        default_factory=lambda: {
            "global_tunable": [
                "trend_atr_fraction",
                "spread_atr_fraction",
                "momentum_atr_fraction",
                "neutral_slope_atr_fraction",
                "band_multiplier",
            ],
            "per_tf_tunable": [
                "window_size",
                "methods.theil_sen.weight",
                "methods.vwr.weight",
                "slope_acceleration_alpha",
            ],
            "per_asset_tunable": [
                "window_size",
                "ensemble.params",
            ],
        }
    )


# ── Resolved Config (output of the resolver) ──


@dataclass(frozen=True)
class ResolvedPipelineConfig:
    """Fully resolved config for a single (asset, timeframe) pair.

    Produced by ConfigResolver.resolve(). Immutable after creation.
    """

    asset: str
    timeframe: str
    asset_class: str
    volume_profile: VolumeProfile
    config_hash: str  # deterministic hash for provenance

    # Pipeline parameters
    window_size: int
    min_window: int
    max_window: int
    atr_period: int
    trend_atr_fraction: float
    spread_atr_fraction: float
    momentum_atr_fraction: float
    neutral_slope_atr_fraction: float
    band_multiplier: float
    slope_acceleration_alpha: float

    # Plugins
    features: tuple  # Tuple[PluginConfig, ...] — frozen
    methods: tuple  # Tuple[Tuple[str, PluginConfig], ...] — frozen
    ensemble: PluginConfig
    uncertainty: PluginConfig

    # Session handling (from asset class)
    session_gap_handling: bool
    low_liquidity_window_handling: bool

    # Regime
    regime_context_enabled: bool
    regime_window_override: bool

    # MTF
    mtf_enabled: bool
    mtf_timeframes: tuple  # Tuple[str, ...] — frozen

    def get_method_configs(self) -> Dict[str, PluginConfig]:
        """Return methods as a mutable dict (convenience for pipeline)."""
        return dict(self.methods)

    def get_feature_configs(self) -> List[PluginConfig]:
        """Return features as a mutable list (convenience for pipeline)."""
        return list(self.features)
