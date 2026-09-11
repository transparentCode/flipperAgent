"""
S/R v2 Models
=============
Immutable data structures for the kernel-ensemble pipeline.

All models are frozen dataclasses built for the current runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class LevelType(Enum):
    """Type of S/R level (canonical definition, formerly in app.sr.models)."""
    SUPPORT = 1
    RESISTANCE = 2


class ZoneStatus(Enum):
    """Zone lifecycle states (§2D state machine)."""
    FORMING = auto()
    ACTIVE = auto()
    TESTED = auto()
    BROKEN = auto()
    FALSE_BREAKOUT = auto()
    FLIPPED = auto()
    EXPIRED = auto()


class ConfluenceTier(Enum):
    """Discrete zone quality tier — human-interpretable rating."""
    S = "S"  # 3+ kernels, MTF confirmed, volume aligned, battle-tested
    A = "A"  # 2 kernels, some MTF/volume, tested
    B = "B"  # 1 structural kernel or 2 micro, partially confirmed
    C = "C"  # 1 micro-only kernel, untested, no volume


class GapBreakoutPolicy(Enum):
    """How gaps interact with breakout confirmation (§2F)."""
    GAP_CONFIRMS_BREAK = "gap_confirms_break"
    GAP_SUSPENDS_COUNTDOWN = "gap_suspends_countdown"
    GAP_IGNORED = "gap_ignored"


class RoundNumberMode(Enum):
    """Round number interval method (§2L)."""
    DECIMAL = "decimal"
    PIP = "pip"


# ---------------------------------------------------------------------------
# Asset Metadata
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AssetMetadata:
    """
    Describes an asset's market structure.

    Loaded from the ``asset_metadata`` config section.  Drives kernel
    activation, gap handling, and rule-derived defaults.

    No pipeline code should branch on ``profile`` — use the boolean /
    numeric / enum fields instead.
    """
    profile: str
    trading_hours_per_day: float
    trading_days_per_week: int
    has_session_gaps: bool
    gap_breakout_policy: str
    gap_escalation_atr: float
    session_lookback_hours: List[int]
    round_number_mode: str
    ex_dividend_filter: bool
    continuous_market: bool
    avg_gap_size_atr: float = 0.0  # populated at runtime by data layer


# ---------------------------------------------------------------------------
# Asset Characteristics (runtime-computed)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AssetCharacteristics:
    """
    Runtime-computed characteristics for a specific (asset, timeframe) pair.

    Combines config-driven ``AssetMetadata`` with data-derived measurements.
    """
    metadata: AssetMetadata

    # Market data (computed at pipeline runtime)
    price: float
    atr: float
    atr_pct: float
    volume_mean: float
    volume_kurtosis: float
    hurst: float
    hurst_confidence: float

    # Wick noise (data-derived)
    wick_body_ratio: float = 1.0  # median(wick_range / body_range); 1.0 = neutral

    # Microstructure percentiles (data-derived)
    wick_p75_atr: float = 0.5    # 75th percentile of wick extent / ATR
    body_p50_atr: float = 0.3    # median body size / ATR
    range_p90_atr: float = 1.5   # 90th percentile full-range / ATR

    # Pipeline context
    tf_minutes: int = 60
    n_timeframes: int = 1


# ---------------------------------------------------------------------------
# Candidate Level (kernel output)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CandidateLevel:
    """
    Immutable raw candidate from a single kernel.

    Zone-aware: all kernels produce center + bounds.  Point-centric kernels
    (pivot_hl, round_number) set bounds to center ± default half-width
    (typically 0.1 × ATR).  Zone-centric kernels (FVG, order_block, VAH/VAL)
    set natural bounds directly.
    """
    center_price: float
    lower_bound: float
    upper_bound: float
    level_type: LevelType
    kernel_name: str
    timeframe: str
    raw_score: float  # kernel-specific quality [0, 1] — NOT calibrated
    metadata: Dict[str, Any]
    timestamp: datetime
    atr_at_detection: float

    @property
    def width_atr(self) -> float:
        """Zone width in ATR units."""
        if self.atr_at_detection <= 0:
            return 0.0
        return (self.upper_bound - self.lower_bound) / self.atr_at_detection


# ---------------------------------------------------------------------------
# Feature Vector
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LevelFeatureVector:
    """
    Typed feature vector per candidate level (§2B).

    Computed by ``LevelFeatureBuilder`` from candidate + market context.
    """
    touch_count: int = 0
    rejection_ratio: float = 0.0
    volume_at_touches: float = 0.0
    time_since_formation: float = 0.0
    cluster_density: float = 0.0
    atr_distance_from_price: float = 0.0
    poc_distance_atr: float = 0.0
    value_area_overlap: float = 0.0
    mtf_confluence_count: int = 0
    breakout_recency: float = 0.0
    volume_trend_at_level: float = 0.0
    wick_depth_max_atr: float = 0.0
    false_breakout_count: int = 0
    kernel_agreement: int = 0
    gap_proximity_atr: float = 0.0
    gap_direction_alignment: float = 0.0
    regime_alignment: float = 0.0  # default neutral when regime unavailable

    # Cross-asset features (Phase 4 — populated by CrossAssetSRAnalyzer)
    universe_agreement: int = 0  # correlated assets with S/R at same relative level
    sector_cluster: float = 0.0  # density of S/R in sector at this price percentile
    dominant_alignment: float = 0.0  # 1.0 if dominant/index asset has aligned S/R
    
    # Extensibility: Any custom features added by extended builders
    extra_features: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Scored Level (ensemble output)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoredLevel:
    """Level with ensemble-computed strength, confidence, and zone quality."""
    candidate: CandidateLevel
    features: LevelFeatureVector
    strength: float
    confidence: float
    contributing_kernels: List[str]
    ensemble_method: str
    zone_quality: float = 0.0          # Composite ZQS: single 0-1 score for position sizing
    confluence_tier: str = "C"         # ConfluenceTier value: S/A/B/C


# ---------------------------------------------------------------------------
# Rule-Derived Parameters
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RuleDerivedParams:
    """
    Parameters computed from asset characteristics via configurable formulas.

    See §2J and §2L for derivation details and formula coefficients.
    """
    # Pivot
    n1: int
    n2: int

    # Fractal channel
    fractal_period: int
    fractal_buffer: float

    # Round number
    round_interval: float

    # Zone width caps
    max_zone_width_atr: float
    max_zone_width_pct: float

    # Invalidation timing
    breakout_confirm_bars: int
    false_breakout_window: int
    inactivity_threshold: int
    max_active_zones: int

    # Volume spike
    volume_spike_threshold: float

    # Wick-adaptive lifecycle
    breakout_atr_threshold: float = 0.3
    touch_proximity_atr: float = 0.1
    false_breakout_recovery_bars: int = 6

    # Temporal adaptation (timeframe-normalized)
    inactivity_decay: float = 0.8

    # Spatial thresholds (data-derived from microstructure)
    merge_threshold_pct_atr: float = 0.25
    dedup_proximity_atr: float = 0.5
    zone_half_width_atr: float = 0.1

    # VP lookbacks
    vp_lookback_hours: List[int] = field(default_factory=list)

    @property
    def lifecycle_params(self) -> Dict[str, Any]:
        """Lifecycle-related params as dict (for config merge)."""
        return {
            "breakout_confirm_bars": self.breakout_confirm_bars,
            "false_breakout_window": self.false_breakout_window,
            "inactivity_threshold": self.inactivity_threshold,
            "inactivity_decay": self.inactivity_decay,
            "max_active_zones": self.max_active_zones,
            "breakout_atr_threshold": self.breakout_atr_threshold,
            "touch_proximity_atr": self.touch_proximity_atr,
            "false_breakout_recovery_bars": self.false_breakout_recovery_bars,
            "dedup_proximity_atr": self.dedup_proximity_atr,
        }

    @property
    def pipeline_params(self) -> Dict[str, Any]:
        """Pipeline-related params as dict (for config merge)."""
        return {
            "merge_threshold_pct_atr": self.merge_threshold_pct_atr,
        }

    @property
    def enhancement_params(self) -> Dict[str, Any]:
        """Enhancement-related params as dict (for config merge)."""
        return {
            "volume_spike_threshold": self.volume_spike_threshold,
        }


# ---------------------------------------------------------------------------
# Zone Lifecycle Event
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ZoneLifecycleEvent:
    """Immutable record of a zone state transition (§2D audit trail)."""
    zone_id: str
    timestamp: datetime
    from_state: ZoneStatus
    to_state: ZoneStatus
    trigger: str
    price_at_event: float
    volume_at_event: float
    bar_index: int
    metadata: Dict[str, Any] = field(default_factory=dict)
