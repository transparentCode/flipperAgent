"""
Output contracts for Regime Orchestrator.

Defines the interfaces between:
- Change Detector (BCPD) → ChangePointSignal
- HMM Classifier → HMMState
- Volatility Overlay → VolState
- Feature Aggregator → RegimeFeatures
"""

from dataclasses import dataclass, field
from typing import Dict, Any
import pandas as pd


@dataclass
class ChangePointSignal:
    """Output from BCPD Change Detection Module."""
    timestamp: pd.Timestamp

    # Core BCPD signals
    change_point_prob: float       # 0.0 - 1.0
    run_length: int                # Bars since last change point
    magnitude: float               # Size of change (z-score)
    change_detected: bool = False  # True when change_point_prob > signal_threshold
    entropy: float = 0.0           # Run-length distribution entropy (high = uncertain)

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HMMState:
    """Output from HMM Classifier Module."""
    p_trending: float         # P(TRENDING | data[0:t])
    p_non_trending: float     # 1 - p_trending
    hmm_regime: str           # "TRENDING" | "NON_TRENDING"
    model_age_bars: int       # Bars since last retrain
    transition_prob: float = 0.5  # P(stay in current state) from transition matrix
    crisis_prob: float = 0.0      # P(crisis state), 0 if 2-state model
    n_states: int = 2             # Number of HMM states used
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VolState:
    """Output from Volatility Overlay Module."""
    vol_percentile: float    # 0–100
    vol_regime: str          # "LOW_VOL" | "HIGH_VOL"
    rolling_vol: float       # Raw rolling std (for adaptive params)


@dataclass
class RegimeFeatures:
    """
    Unified output from Feature Aggregator.

    Consumed by:
    - Strategy (for position sizing, stops, holding periods)
    - Regression orchestrator (via RegimeSnapshot)
    - Charts / export pipeline
    """
    timestamp: pd.Timestamp

    # Combined regime label (9 states)
    # Trend:     CLEAN_TREND_BULL | CLEAN_TREND_BEAR | CLEAN_TREND_FLAT
    #            VOLATILE_TREND_BULL | VOLATILE_TREND_BEAR | VOLATILE_TREND_FLAT
    # Non-trend: QUIET_MR_RANGE | QUIET_MR_SQUEEZE | CHOPPY
    regime: str

    # Key signals (flat, for fast access)
    p_trending: float         # from HMM
    vol_percentile: float     # from vol overlay
    changepoint_prob: float   # from BCPD
    adaptive_period: int      # from Hilbert → aggregator

    # Trading parameters (regime-specific)
    position_scale: float
    atr_multiplier: float            # regime-specific stop distance
    holding_period: int              # regime-specific max hold bars

    # Raw component states (for debugging / downstream use)
    hmm_state: HMMState
    vol_state: VolState
    change_signal: ChangePointSignal
    hilbert_period: float
    hilbert_confidence: float
