from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


class DegradationLevel(enum.Enum):
    """First-class degradation state on every result."""

    FULL = "full"  # all stages ran successfully
    PARTIAL = "partial"  # some methods/features degraded but ensemble is valid
    FALLBACK = "fallback"  # primary path failed, using fallback logic
    FAILED = "failed"  # pipeline could not produce valid output


@dataclass
class FeatureSet:
    """Standardized feature set passed from feature extractors to methods."""

    valid_mask: np.ndarray  # bool, accumulated AND across extractors
    timestamps: np.ndarray
    close_raw: np.ndarray
    log_prices: np.ndarray
    weights: np.ndarray  # volume-transformed, mean=1.0

    volume_raw: np.ndarray
    volume_clipped: Optional[np.ndarray] = None
    session_mask: Optional[np.ndarray] = None  # True = valid session bar

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MethodResult:
    """Output from a single regression method."""

    method_name: str
    slope: float
    intercept: float
    center: np.ndarray  # price-space mid-line
    confidence: float  # 0.0–1.0
    r_squared: float

    upper: Optional[np.ndarray] = None  # price-space upper band
    lower: Optional[np.ndarray] = None  # price-space lower band
    is_valid: bool = True
    band_type: str = "log_mad"  # "log_mad" | "covariance" | "quantile"
    degradation: DegradationLevel = DegradationLevel.FULL
    warm_up_bars_needed: int = 0

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EnsembleResult:
    """Output from the ensemble strategy."""

    center: float
    slope: float = 0.0
    intercept: float = 0.0
    direction: str = "NEUTRAL"
    upper: Optional[float] = None
    lower: Optional[float] = None
    confidence: float = 0.0
    is_valid: bool = True
    degradation: DegradationLevel = DegradationLevel.FULL

    # v2 additions
    agreement_score: float = 0.0  # method agreement (0 = disagree, 1 = fully agree)
    dominant_method: str = ""
    method_weights: Dict[str, float] = field(default_factory=dict)

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RegressionResult:
    """Final output from pipeline for a single (asset, timeframe) computation."""

    # Identity
    asset: str
    timeframe: str
    timestamp: datetime
    config_hash: str

    # Core outputs
    slope: float
    direction: str
    confidence: float
    upper_band: np.ndarray
    lower_band: np.ndarray
    mid_line: np.ndarray
    band_width_avg: float
    atr_norm: float  # ATR / price
    z_score: float  # (close - center) / band_half_width

    # Method detail
    method_outputs: Dict[str, MethodResult]
    method_weights: Dict[str, float]

    # Ensemble detail
    ensemble_result: EnsembleResult

    # Signals
    signals: List[str] = field(default_factory=list)

    # Pipeline state
    window_used: int = 0
    warm_up_bars_needed: int = 0
    is_warmed_up: bool = True
    bars_since_init: int = 0
    regime_applied: bool = False
    mtf_applied: bool = False
    is_valid: bool = True
    degradation: DegradationLevel = DegradationLevel.FULL

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MTFOutput:
    """Output from multi-timeframe cascade for a single asset."""

    asset: str
    per_tf: Dict[str, RegressionResult]
    alignment_score: float  # [-1, +1]
    direction_consensus: str
    consensus_strength: float
    dominant_tf: str
    dominant_result: RegressionResult
    is_conflicted: bool
    conflict_pairs: List[Tuple[str, str]]
    weighted_slope: float
    weighted_confidence: float
    all_warmed_up: bool
    degradation: DegradationLevel = DegradationLevel.FULL
    config_hash: str = ""


@dataclass
class UniverseResult:
    """Output from processing a universe of assets."""

    results: Dict[str, RegressionResult]  # keyed by asset
    mtf_results: Dict[str, MTFOutput]  # keyed by asset (only for mtf_enabled assets)

    n_assets_processed: int = 0
    n_degraded: int = 0
    n_failed: int = 0
    processing_time_ms: float = 0.0
    config_hash: str = ""  # hash of universe config
