from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field
from numbers import Real
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


@dataclass
class PluginConfig:
    name: str
    enabled: bool = True
    weight: float = 1.0
    params: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)


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

    # Pipeline parameters
    atr_period: int = 14
    band_multiplier: float = 2.0

    # Window bounds for configuration validation
    min_window: int = 15
    max_window: int = 300
    default_window_size: int = 100


# ── Tier 2: Per-Timeframe Defaults ──


@dataclass
class TimeframeConfig:
    """Tier 2: per-timeframe overrides. None fields inherit from global."""

    window_size: Optional[int] = None
    band_multiplier: Optional[float] = None

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
    band_multiplier: Optional[float] = None
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
    band_multiplier: Optional[float] = None
    methods: Optional[Dict[str, PluginConfig]] = None
    ensemble: Optional[PluginConfig] = None


@dataclass(frozen=True)
class StructuralChannelConfig:
    """YAML-owned empirical coverages for structural channel geometry."""

    inner_coverage: float
    outer_coverage: float

    def __post_init__(self) -> None:
        inner = _validated_coverage(self.inner_coverage, "inner_coverage")
        outer = _validated_coverage(self.outer_coverage, "outer_coverage")
        if not 0.0 < inner < outer < 1.0:
            raise ValueError(
                "structural channel coverages must satisfy "
                "0 < inner_coverage < outer_coverage < 1"
            )
        object.__setattr__(self, "inner_coverage", inner)
        object.__setattr__(self, "outer_coverage", outer)


# ── Orchestrator Config ──


@dataclass
class OrchestratorConfig:
    """Top-level config: wraps all tiers."""

    # MTF settings (for assets that have mtf_enabled=True)
    mtf_timeframes: List[str] = field(
        default_factory=lambda: ["4h", "1h", "30m"]
    )
    tf_weights: Dict[str, float] = field(
        default_factory=lambda: {"4h": 0.5, "1h": 0.3, "30m": 0.2}
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
                "band_multiplier",
            ],
            "per_tf_tunable": [
                "window_size",
            ],
            "per_asset_tunable": [
                "window_size",
            ],
        }
    )
    structural_channel: StructuralChannelConfig | None = None


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
    band_multiplier: float

    # Plugins
    features: tuple  # Tuple[PluginConfig, ...] — frozen
    methods: tuple  # Tuple[Tuple[str, PluginConfig], ...] — frozen
    ensemble: PluginConfig
    uncertainty: PluginConfig

    # Session handling (from asset class)
    session_gap_handling: bool
    low_liquidity_window_handling: bool

    # MTF
    mtf_enabled: bool
    mtf_timeframes: tuple  # Tuple[str, ...] — frozen

    def get_method_configs(self) -> Dict[str, PluginConfig]:
        """Return methods as a mutable dict (convenience for pipeline)."""
        return dict(self.methods)

    def get_feature_configs(self) -> List[PluginConfig]:
        """Return features as a mutable list (convenience for pipeline)."""
        return list(self.features)


def _validated_coverage(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a finite numeric coverage")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{name} must be a finite numeric coverage")
    return numeric
