"""Python fallback when trendlines.yaml is absent."""
from __future__ import annotations

from typing import Any, Dict


def get_default_config_dict() -> Dict[str, Any]:
    """Mirror of trendlines.yaml as a Python dict. Used as fallback."""
    return {
        "pipeline": {
            "extractor": "fractal",
            "fitter": "pathfinding",
        },
        "defaults": {
            "interaction_tolerance_atr": 0.25,
            "asymmetry_threshold": 0.3,
            "convergence_rate_threshold": 0.2,
            "wick_rejection_ratio": 0.5,
            "squeeze_threshold": 3.0,
        },
        "assets": {},
        "signal_weights": {
            "default_weight": 1.0,
            "weights": {},
        },
        "protocol": {
            "fitness": {
                "slope_tolerance": 0.25,
                "min_tolerance_atr_frac": 0.1,
                "consecutive_penetration_bars": 3,
                "forward_lookahead_bars": 3,
                "touch_accuracy_floor": 0.01,
                "pivot_count_min": 5,
                "pivot_density_min": 2.0,
                "pivot_density_optimal_lo": 8.0,
                "pivot_density_optimal_hi": 25.0,
                "line_count_penalty_threshold": 6,
                "line_count_penalty_factor": 0.1,
            },
            "walk_forward": {
                "train_bars": 2160,
                "test_bars": 720,
                "step_bars": 720,
                "purge_bars": 24,
                "min_train_bars": 1440,
            },
            "lookback_grid": {
                "fractions": [0.4, 0.6, 0.8],
                "min_bars": 20,
            },
            "drift_monitor": {
                "threshold": 0.15,
            },
        },
        "search_grids": {
            "fractal": {
                "left_windows": [3, 5, 7, 10],
                "right_windows": [3, 5, 7, 10],
            },
            "rdp_zigzag": {
                "epsilon_atr_values": [0.2, 0.3, 0.5, 0.8, 1.0],
                "min_segment_bars_values": [1, 3, 5],
            },
            "pathfinding": {
                "pivot_windows": [2, 3, 5],
            },
            "least_squares": {
                "pivot_windows": [2, 3, 5],
                "residual_thresholds": [0.3, 0.5, 0.8],
            },
            "ransac": {
                "pivot_windows": [2, 3],
                "residual_thresholds": [0.3, 0.5],
                "max_cut_fractions": [0.1, 0.2],
            },
        },
    }
