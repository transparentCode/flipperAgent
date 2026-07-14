"""
Shared Optimization Constants & Utilities
==========================================
Central home for parameter space definitions, default values, and
utility functions used across the optimization module.

Previously scattered across ``universe_optimizer.py``,
``asset_optimizer.py``, and ``two_stage_optimizer.py``.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict

from app.sr.config_schema import OptimizationParameterConfig

# Re-export the canonical spec type under a friendlier alias
OptimizationParameterSpec = OptimizationParameterConfig


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# Params that may only be tuned at the global (Stage 1) level
GLOBAL_ONLY_PARAMS = frozenset({
    "ensemble.structural_vs_micro_ratio",
    "lifecycle.age_lambda",
    "cross_asset.sector_cluster_eps_atr",
})

# Gate params — tuned per-asset (Stage 2), centred on resolved YAML value
GATE_PARAMS = frozenset({
    "pipeline.min_emit_strength",
    "pipeline.max_new_zones_per_bar",
})

# Stage 2 only params — skipped during Stage 1
STAGE2_ONLY_PARAMS = frozenset({
    "pipeline.min_emit_strength",
    "pipeline.max_new_zones_per_bar",
})

# Shared results directory
RESULTS_DIR = Path(__file__).parent / "results"


# ---------------------------------------------------------------------------
# Canonical parameter space
# ---------------------------------------------------------------------------

def default_parameter_space() -> Dict[str, OptimizationParameterSpec]:
    """Return the 18-param search space with Sobol sensitivity rankings.

    Only 5 params (ST > 0.05) are enabled by default.  Override
    per-param via ``sr.yaml optimization.parameters.<name>.enabled``.
    """
    return {
        # --- HIGH sensitivity (ST > 0.05) — OPTIMIZE ---
        "lifecycle.dedup_proximity_atr": OptimizationParameterSpec(0.3, 1.5),          # ST=0.775
        "pipeline.merge_threshold_pct_atr": OptimizationParameterSpec(0.15, 0.6),      # ST=0.582
        "kernels.anchored_vwap.volume_spike_multiplier": OptimizationParameterSpec(1.5, 3.5),  # ST=0.236
        "kernels.tpo_value_area.tpo_value_area_pct": OptimizationParameterSpec(0.60, 0.85),    # ST=0.101
        "lifecycle.min_strength": OptimizationParameterSpec(0.2, 0.6),                 # ST=0.097

        # --- MEDIUM sensitivity (0.01 < ST < 0.05) — frozen by default ---
        "lifecycle.age_lambda": OptimizationParameterSpec(0.0015, 0.0035, enabled=False),            # ST=0.041
        "kernels.order_block.imbalance_ratio": OptimizationParameterSpec(0.55, 0.85, enabled=False), # ST=0.030
        "kernels.fair_value_gap.fill_threshold": OptimizationParameterSpec(0.35, 0.65, enabled=False),  # ST=0.022
        "kernels.fair_value_gap.gap_min_atr": OptimizationParameterSpec(0.35, 0.9, enabled=False),   # ST=0.020
        "kernels.order_block.displacement_atr": OptimizationParameterSpec(1.0, 2.2, enabled=False),  # ST=0.010

        # --- LOW sensitivity (ST < 0.01) — frozen by default ---
        "lifecycle.auto_promote_kernel_agreement": OptimizationParameterSpec(1, 4, kind="int", enabled=False),  # ST=0.005
        "kernels.fair_value_gap.filled_penalty_multiplier": OptimizationParameterSpec(0.25, 0.75, enabled=False),  # ST=0.002
        "ensemble.structural_vs_micro_ratio": OptimizationParameterSpec(0.4, 0.65, enabled=False),   # ST=0.000
        "cross_asset.sector_cluster_eps_atr": OptimizationParameterSpec(0.4, 0.9, enabled=False),    # ST=0.000
        "kernels.volume_poc.hvn_prominence": OptimizationParameterSpec(0.1, 0.35, enabled=False),    # ST=0.000
        "kernels.regression_band.band_width_sigma": OptimizationParameterSpec(1.5, 2.75, enabled=False),  # ST=0.000
        "kernels.liquidity_sweep.sweep_lookback": OptimizationParameterSpec(30, 80, kind="int", enabled=False),  # ST=0.000
        "kernels.liquidity_sweep.max_pierce_atr": OptimizationParameterSpec(0.5, 1.4, enabled=False),  # ST=0.000

        # --- Gated / Stage 2 only ---
        "kernels.session_gap.gap_min_atr": OptimizationParameterSpec(
            0.35, 0.9, enabled=False, metadata_gate="has_session_gaps",
        ),
        "pipeline.min_emit_strength": OptimizationParameterSpec(0.15, 0.40),
        "pipeline.max_new_zones_per_bar": OptimizationParameterSpec(2, 5, kind="int"),
    }


DEFAULT_PARAM_VALUES: Dict[str, float] = {
    "ensemble.structural_vs_micro_ratio": 0.5,
    "lifecycle.age_lambda": 0.002,
    "lifecycle.min_strength": 0.3,
    "lifecycle.auto_promote_kernel_agreement": 2,
    "lifecycle.dedup_proximity_atr": 0.5,
    "pipeline.merge_threshold_pct_atr": 0.25,
    "cross_asset.sector_cluster_eps_atr": 0.5,
    "kernels.anchored_vwap.volume_spike_multiplier": 2.0,
    "kernels.volume_poc.hvn_prominence": 0.2,
    "kernels.fair_value_gap.gap_min_atr": 0.5,
    "kernels.fair_value_gap.fill_threshold": 0.5,
    "kernels.fair_value_gap.filled_penalty_multiplier": 0.5,
    "kernels.order_block.displacement_atr": 1.5,
    "kernels.order_block.imbalance_ratio": 0.7,
    "kernels.regression_band.band_width_sigma": 2.0,
    "kernels.liquidity_sweep.sweep_lookback": 50,
    "kernels.liquidity_sweep.max_pierce_atr": 1.0,
    "kernels.tpo_value_area.tpo_value_area_pct": 0.68,
    "kernels.session_gap.gap_min_atr": 0.5,
    "pipeline.min_emit_strength": 0.25,
    "pipeline.max_new_zones_per_bar": 3,
}


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge *overlay* into a deep copy of *base*."""
    result = copy.deepcopy(base)
    for key, val in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def flat_to_nested(params: Dict[str, float]) -> Dict[str, Any]:
    """Convert flat dotted param names to a nested dict.

    Example: ``{"a.b.c": 1}`` → ``{"a": {"b": {"c": 1}}}``.
    """
    result: Dict[str, Any] = {}
    for name, value in params.items():
        parts = name.split(".")
        cursor = result
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return result


# ---------------------------------------------------------------------------
# Backward-compatible aliases (underscore-prefixed names)
# ---------------------------------------------------------------------------
# Tests and other modules imported these with leading underscores.
# Keep aliases so existing imports don't break.

_default_parameter_space = default_parameter_space
_DEFAULT_PARAM_VALUES = DEFAULT_PARAM_VALUES
_deep_merge = deep_merge
_flat_to_nested = flat_to_nested
_GLOBAL_ONLY_PARAMS = GLOBAL_ONLY_PARAMS
_GATE_PARAMS = GATE_PARAMS
_STAGE2_ONLY_PARAMS = STAGE2_ONLY_PARAMS
_RESULTS_DIR = RESULTS_DIR
