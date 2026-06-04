"""Constants for RegimeClassification optimization pipeline.

All magic numbers, thresholds, weights, and defaults live here.
Implementation files import from this module — no inline hardcoding.
"""

from __future__ import annotations

# ── Study Configuration ──────────────────────────────────────────────

SCREENING_TRIALS: int = 50
MAIN_TRIALS: int = 150
CONVERGENCE_PATIENCE: int = 50
SEED: int = 42

STUDY_DIRECTION: str = "maximize"
STUDY_SAMPLER: str = "TPE"
# No pruner — each trial is a full batch_evaluate, not iterative
STUDY_PRUNER: str = "NopPruner"

# ── Composite Quality Weights ────────────────────────────────────────
# Weights for the 5 quality components in composite_quality.
# Must sum to 1.0.

WEIGHT_CH_SCORE: float = 0.25
WEIGHT_AVG_RUN_LENGTH: float = 0.20
WEIGHT_RETURN_SPREAD: float = 0.20
WEIGHT_HURST_FWD_CORR: float = 0.20
WEIGHT_VOL_CALIBRATION: float = 0.15

# ── Quality Metric Normalization ─────────────────────────────────────
# Upper bounds for normalizing raw metrics to [0, 1].

CH_SCORE_NORMALIZER: float = 100.0
AVG_RUN_LENGTH_NORMALIZER: float = 20.0
RETURN_SPREAD_NORMALIZER_BPS: float = 5.0

# ── Quality Forward Return Horizons ──────────────────────────────────

FORWARD_RETURN_HORIZON_SHORT: int = 10
FORWARD_RETURN_HORIZON_LONG: int = 20
ROLLING_VOL_WINDOW: int = 5

# ── Minimum Sample Sizes ────────────────────────────────────────────

MIN_SAMPLES_FOR_METRIC: int = 50
MIN_SAMPLES_PER_STATE: int = 10
MIN_BARS_FOR_QUALITY: int = 500

# ── OOS Gate ─────────────────────────────────────────────────────────
# Regime uses quality-based gating, not Sharpe-based.
# Tighter than direction models (0.50) because quality metrics are less volatile.

OOS_QUALITY_RATIO: float = 0.70

# ── Calibration Defaults ─────────────────────────────────────────────
# Used by calibration.py for offline param derivation.

CALIBRATION_VOL_LOOKBACK: int = 168          # rolling vol window for crisis_vol_mult calibration
CALIBRATION_VOL_QUANTILE: float = 0.95       # percentile for crisis threshold
CALIBRATION_CP_MIN_DISTANCE: int = 10        # minimum bars between changepoints
CALIBRATION_CP_PENALTY: str = "l2"           # ruptures penalty type
CALIBRATION_CP_MODEL: str = "rbf"            # ruptures cost model

# ── Kernel Param Search Ranges ───────────────────────────────────────
# Search bounds for frozen kernel params exposed to Optuna.
# The 5 tunable params already have ranges in hyperparameter_schema.

RETRAIN_WINDOW_LOW: int = 200
RETRAIN_WINDOW_HIGH: int = 1000
RETRAIN_WINDOW_STEP: int = 50

VOL_LOOKBACK_LOW: int = 72
VOL_LOOKBACK_HIGH: int = 500
VOL_LOOKBACK_STEP: int = 24

TREND_LOOKBACK_LOW: int = 10
TREND_LOOKBACK_HIGH: int = 60
TREND_LOOKBACK_STEP: int = 5
