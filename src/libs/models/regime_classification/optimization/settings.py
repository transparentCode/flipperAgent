"""YAML-backed settings for RegimeClassification optimization.

The constants module remains the safe import-time fallback. Runtime callers use
this module so experiment knobs can be moved into ``configs/optimization.yaml``
without making optimization code depend on hardcoded values only.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_OPTIMIZATION
from libs.models.regime_classification.optimization import constants as c


DEFAULT_REGIME_OPTIMIZATION_SETTINGS: dict[str, Any] = {
    "study": {
        "screening_trials": c.SCREENING_TRIALS,
        "main_trials": c.MAIN_TRIALS,
        "convergence_patience": c.CONVERGENCE_PATIENCE,
        "seed": c.SEED,
        "direction": c.STUDY_DIRECTION,
        "sampler": c.STUDY_SAMPLER,
        "pruner": c.STUDY_PRUNER,
    },
    "quality": {
        "weights": {
            "ch_score": c.WEIGHT_CH_SCORE,
            "avg_run_length": c.WEIGHT_AVG_RUN_LENGTH,
            "return_spread": c.WEIGHT_RETURN_SPREAD,
            "hurst_fwd_corr": c.WEIGHT_HURST_FWD_CORR,
            "vol_calibration": c.WEIGHT_VOL_CALIBRATION,
        },
        "normalizers": {
            "ch_score": c.CH_SCORE_NORMALIZER,
            "avg_run_length": c.AVG_RUN_LENGTH_NORMALIZER,
            "return_spread_bps": c.RETURN_SPREAD_NORMALIZER_BPS,
        },
        "forward_return_horizon_short": c.FORWARD_RETURN_HORIZON_SHORT,
        "forward_return_horizon_long": c.FORWARD_RETURN_HORIZON_LONG,
        "rolling_vol_window": c.ROLLING_VOL_WINDOW,
        "min_samples_for_metric": c.MIN_SAMPLES_FOR_METRIC,
        "min_samples_per_state": c.MIN_SAMPLES_PER_STATE,
        "min_bars_for_quality": 200,
        "oos_quality_ratio": c.OOS_QUALITY_RATIO,
    },
    "calibration": {
        "vol_lookback": c.CALIBRATION_VOL_LOOKBACK,
        "vol_quantile": c.CALIBRATION_VOL_QUANTILE,
        "cp_min_distance": c.CALIBRATION_CP_MIN_DISTANCE,
        "cp_penalty": c.CALIBRATION_CP_PENALTY,
        "cp_model": c.CALIBRATION_CP_MODEL,
    },
    "kernel_search": {
        "retrain_window": {
            "low": c.RETRAIN_WINDOW_LOW,
            "high": c.RETRAIN_WINDOW_HIGH,
            "step": c.RETRAIN_WINDOW_STEP,
            "default": 500,
        },
        "vol_lookback": {
            "low": c.VOL_LOOKBACK_LOW,
            "high": 480,
            "step": c.VOL_LOOKBACK_STEP,
            "default": 168,
        },
        "trend_lookback": {
            "low": c.TREND_LOOKBACK_LOW,
            "high": c.TREND_LOOKBACK_HIGH,
            "step": c.TREND_LOOKBACK_STEP,
            "default": 20,
        },
    },
    "benchmark_ladder": {
        "cost_bps": 10.0,
        "train_ratio": 0.60,
        "val_ratio": 0.20,
        "purge_bars": 24,
        "shuffle_seed": 42,
        "min_bars": 500,
        "sma_fast": 20,
        "sma_slow": 50,
        "ema_fast": 20,
        "ema_slow": 50,
        "trend_strength_threshold": 0.35,
        "max_vol_percentile": 85.0,
        "max_changepoint_prob": 0.65,
        "max_crisis_prob": 0.50,
        "min_sharpe_lift": 0.10,
        "min_calmar_lift": 0.05,
        "min_total_return_lift": 0.0,
        "min_oos_sharpe": 0.0,
        "min_oos_total_return": 0.0,
        "min_avg_position": 0.05,
    },
    "alpha_ladder": {
        "n_trials": 80,
        "seed": c.SEED,
        "min_bars": 500,
        "shuffle_seed": c.SEED,
        "null_controls": ["circular_shift", "block_shuffle"],
        "null_shift_bars": 720,
        "null_block_bars": 96,
        "turnover_penalty": 0.05,
        "policy_regularization": 0.0,
        "policy_kinds": [
            "risk_filtered",
            "trend_scaled",
            "confidence_scaled",
            "combined",
            "soft_scaled",
        ],
        "max_vol_percentile_low": 55.0,
        "max_vol_percentile_high": 100.0,
        "max_changepoint_prob_low": 0.05,
        "max_changepoint_prob_high": 0.95,
        "max_crisis_prob_low": 0.0,
        "max_crisis_prob_high": 0.95,
        "min_trend_strength_low": 0.0,
        "min_trend_strength_high": 0.80,
        "min_confidence_low": 0.0,
        "min_confidence_high": 0.95,
        "trend_power_low": 0.50,
        "trend_power_high": 3.0,
        "min_position_scale_low": 0.0,
        "min_position_scale_high": 0.50,
    },
    "descriptor_ladder": {
        "min_bars": 500,
        "train_ratio": 0.60,
        "val_ratio": 0.20,
        "purge_bars": 24,
        "shuffle_seed": c.SEED,
        "null_controls": ["circular_shift", "block_shuffle"],
        "null_shift_bars": 720,
        "null_block_bars": 96,
        "min_abs_oos_ic": 0.03,
        "min_ic_lift_vs_null": 0.0,
        "min_stable_descriptor_pairs": 2,
        "min_median_abs_oos_ic": 0.02,
        "min_median_ic_lift_vs_null": 0.0,
        "descriptor_targets": [
            {"descriptor": "trend_strength", "target": "fwd_abs_return_5"},
            {"descriptor": "vol_percentile", "target": "fwd_vol_5"},
            {"descriptor": "fwd_vol_ewma", "target": "fwd_vol_5"},
            {"descriptor": "changepoint_prob", "target": "fwd_abs_return_1"},
            {"descriptor": "hmm_crisis_prob", "target": "fwd_abs_return_5"},
            {"descriptor": "cp_entropy", "target": "fwd_abs_return_5"},
            {"descriptor": "hurst", "target": "fwd_abs_return_10"},
        ],
    },
    "rolling_descriptor_ladder": {
        "fold_bars": 2160,
        "step_bars": 720,
        "min_folds": 2,
        "min_pass_rate": 0.60,
        "min_promoted_folds": 2,
        "min_median_abs_oos_ic": 0.02,
        "min_median_ic_lift_vs_null": 0.0,
    },
    "volatility_ladder": {
        "min_bars": 500,
        "train_ratio": 0.60,
        "val_ratio": 0.20,
        "purge_bars": 24,
        "forecast_column": "fwd_vol_ewma",
        "shuffle_seed": c.SEED,
        "null_controls": ["circular_shift", "block_shuffle"],
        "null_shift_bars": 720,
        "null_block_bars": 96,
        "policy_kinds": ["inverse_vol", "high_vol_throttle", "vol_rank_scaled"],
        "target_vol_multipliers": [0.75, 1.0, 1.25],
        "min_position_scales": [0.25, 0.50],
        "high_vol_quantiles": [0.60, 0.75, 0.90],
        "high_vol_scales": [0.25, 0.50],
        "rank_powers": [1.0, 2.0],
        "turnover_penalty": 0.05,
        "drawdown_improvement_weight": 1.0,
        "min_sharpe_lift": 0.05,
        "min_calmar_lift": 0.0,
        "min_drawdown_improvement": 0.0,
        "min_avg_position": 0.05,
    },
    "rolling_volatility_ladder": {
        "fold_bars": 2160,
        "step_bars": 720,
        "min_folds": 2,
        "min_pass_rate": 0.60,
        "min_promoted_folds": 2,
        "min_median_sharpe_lift": 0.05,
        "min_median_null_sharpe_lift": 0.0,
        "min_median_drawdown_improvement": 0.0,
    },
    "probability_ladder": {
        "min_bars": 500,
        "train_ratio": 0.60,
        "val_ratio": 0.20,
        "purge_bars": 24,
        "forecast_column": "fwd_vol_ewma",
        "target_horizon": 5,
        "shuffle_seed": c.SEED,
        "null_controls": ["circular_shift", "block_shuffle"],
        "null_shift_bars": 720,
        "null_block_bars": 96,
        "event_quantiles": [0.70, 0.75, 0.80],
        "n_bins_grid": [4, 5, 8],
        "risk_budgets": [0.25, 0.50, 0.75],
        "min_position_scales": [0.25, 0.50],
        "smoothing": 2.0,
        "brier_weight": 2.0,
        "null_lift_weight": 1.0,
        "null_brier_weight": 1.0,
        "min_oos_auc": 0.55,
        "min_auc_lift_vs_null": 0.0,
        "min_brier_lift_vs_null": 0.0,
        "min_sharpe_lift": 0.05,
        "min_null_sharpe_lift": 0.0,
        "min_drawdown_improvement": 0.0,
        "min_avg_position": 0.05,
    },
    "rolling_probability_ladder": {
        "fold_bars": 2160,
        "step_bars": 720,
        "min_folds": 2,
        "min_promoted_folds": 2,
        "min_probability_pass_rate": 0.60,
        "min_median_auc": 0.55,
        "min_median_auc_lift": 0.0,
        "min_median_brier_lift": 0.0,
    },
    "rolling_alpha_ladder": {
        "fold_bars": 2160,
        "step_bars": 720,
        "min_folds": 2,
        "min_pass_rate": 0.60,
        "min_promoted_folds": 2,
        "min_median_oos_sharpe": 0.0,
        "min_median_oos_return": 0.0,
        "min_median_sharpe_lift": 0.10,
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return ``base`` recursively merged with ``override``."""
    merged = deepcopy(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_regime_optimization_settings(
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load regime optimization settings from YAML with safe defaults."""
    settings = deepcopy(DEFAULT_REGIME_OPTIMIZATION_SETTINGS)
    try:
        manager = ConfigManager()
        manager.register_file(CONFIG_FILE_OPTIMIZATION)
        yaml_settings = manager.get("optimization.regime_classification", {}) or {}
        if isinstance(yaml_settings, dict):
            settings = deep_merge(settings, yaml_settings)
    except Exception:
        # Optimization scripts should remain runnable in isolated test contexts.
        pass
    if overrides:
        settings = deep_merge(settings, overrides)
    return settings
