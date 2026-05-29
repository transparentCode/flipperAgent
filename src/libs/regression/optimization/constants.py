"""Shared constants for optimization.

Centralised here to prevent silent divergence from copy-paste definitions.
All magic numbers, thresholds, and structural defaults live in this file.
Runtime-tunable values belong in the YAML config or RegressionOptimizationConfig.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Walk-Forward Defaults
# ---------------------------------------------------------------------------
DEFAULT_TRAIN_BARS: int = 4320        # 6 months of 1h bars
DEFAULT_VALIDATE_BARS: int = 720      # 1 month
DEFAULT_TEST_BARS: int = 720          # 1 month
DEFAULT_STEP_BARS: int = 720          # 1 month step
DEFAULT_PURGE_BARS: int = 24          # 1 day of 1h bars
DEFAULT_MIN_TRAIN_BARS: int = 2160    # 3 months minimum
DEFAULT_MAX_TRAIN_RATIO: float = 0.6  # Cap train set at 60% of total data

# ---------------------------------------------------------------------------
# Optimizer Run Settings
# ---------------------------------------------------------------------------
DEFAULT_N_TRIALS: int = 200
DEFAULT_TIMEOUT_SECONDS: int = 3600
DEFAULT_N_JOBS: int = 1               # >1 not thread-safe, see optimizer.py
DEFAULT_SEED: int = 42                # Reproducible MOTPE sampling

# ---------------------------------------------------------------------------
# Gate / Constraint Thresholds
# ---------------------------------------------------------------------------
DEFAULT_MIN_DURBIN_WATSON: float = 0.5
DEFAULT_MIN_CONFIDENCE_RHO: float = 0.01
DEFAULT_MIN_VALID_RESULTS: int = 20   # Minimum result count per fold eval
MIN_SPEARMAN_SAMPLES: int = 20        # Minimum pairs for Spearman correlation
MIN_RESIDUAL_SAMPLES_FRAC: float = 0.01  # Fraction of closes for DW residuals
MIN_RESIDUAL_SAMPLES_ABS: int = 10       # Absolute minimum for DW residuals

# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
DEFAULT_WORST_CASE_PERCENTILE: int = 10
DEFAULT_MAX_FAILED_FOLDS: int = 10

# ---------------------------------------------------------------------------
# Direction Accuracy
# ---------------------------------------------------------------------------
DEFAULT_DIRECTION_HORIZONS: tuple[int, ...] = (4, 12, 24)
DEFAULT_DIRECTION_HORIZON_WEIGHTS: tuple[float, ...] = (0.5, 0.3, 0.2)

# ---------------------------------------------------------------------------
# Strategy Utility / Annualization
# ---------------------------------------------------------------------------
BARS_PER_YEAR: dict[str, float] = {
    "1m": 525_960.0,
    "5m": 105_120.0,
    "15m": 35_040.0,
    "30m": 17_520.0,
    "1h": 8_760.0,
    "2h": 4_380.0,
    "4h": 2_190.0,
    "6h": 1_460.0,
    "8h": 1_095.0,
    "12h": 730.0,
    "1d": 365.0,
    "1w": 52.0,
}
DEFAULT_BARS_PER_YEAR: float = 8_760.0  # 1h fallback

# ---------------------------------------------------------------------------
# Band Calibration
# ---------------------------------------------------------------------------
DEFAULT_TARGET_COVERAGE: float = 0.95  # 2-sigma Gaussian band target

# ---------------------------------------------------------------------------
# Confidence Correlation
# ---------------------------------------------------------------------------
DEFAULT_CONFIDENCE_HORIZON: int = 12   # Forward-return horizon for Spearman

# ---------------------------------------------------------------------------
# Search Space Defaults
# ---------------------------------------------------------------------------
DEFAULT_PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "window_size": (30, 200),
    "band_multiplier": (1.5, 2.5),
    "trend_atr_fraction": (0.05, 0.20),
    "spread_atr_fraction": (0.08, 0.25),
    "momentum_atr_fraction": (0.05, 0.20),
    "neutral_slope_atr_fraction": (0.02, 0.08),
    "slope_acceleration_alpha": (0.0, 0.5),
    "methods.theil_sen.weight": (0.2, 2.0),
    "methods.vwr.weight": (0.2, 2.0),
}

DEFAULT_PARAM_TYPES: dict[str, str] = {
    "window_size": "int",
}

# ---------------------------------------------------------------------------
# MOTPE Objectives
# ---------------------------------------------------------------------------
DEFAULT_OBJECTIVES: list[str] = [
    "weighted_direction_score",
    "band_coverage_pct",
    "confidence_sharpe",
]
DEFAULT_META_FILTER_METRIC: str = "max_drawdown"
DEFAULT_COVERAGE_CAP: float = 0.92   # Soft cap: coverage above this is equivalent

# ---------------------------------------------------------------------------
# MOTPE Constraint Defaults (feasibility thresholds for Pareto front)
# These apply to worst-case percentile aggregated objectives, not mean.
# Keep loose — the post-hoc quality floor in HarmonicStabilitySelector
# provides strict filtering on benchmark means.
# ---------------------------------------------------------------------------
DEFAULT_MIN_DIRECTION_FLOOR: float = 0.42   # 10th-pctl direction must be >= this
DEFAULT_MIN_SHARPE_FLOOR: float = -2.0      # 10th-pctl sharpe must be >= this

# ---------------------------------------------------------------------------
# Numeric Stability
# ---------------------------------------------------------------------------
EPSILON: float = 1e-10  # Division-by-zero guard
