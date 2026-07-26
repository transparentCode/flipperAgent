"""YAML configuration loader for trendlines."""
from __future__ import annotations

import os
from typing import Any, Dict

import yaml

from .base_config import (
    AssetConfig,
    AssetTimeframeConfig,
    OptimizableDefaults,
    OscillatorDefaults,
    OscillatorOverride,
    SnapshotHistoryOverride,
    SnapshotHistoryPolicy,
    TrendlinesConfig,
)
from .defaults import get_default_config_dict
from .evaluation_config import (
    DriftMonitorConfig,
    EvaluationConfig,
    FitnessConfig,
    LookbackGridConfig,
    WalkForwardDefaults,
)
from .search_grid_config import (
    FractalSearchGrid,
    GridSearchConfig,
    LeastSquaresSearchGrid,
    PathfindingSearchGrid,
    RansacSearchGrid,
    RDPSearchGrid,
)


def _merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = base.copy()
    for k, v in override.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _merge_dicts(merged[k], v)
        else:
            merged[k] = v
    return merged


def _parse_asset_tf_config(raw: Dict[str, Any]) -> AssetTimeframeConfig:
    """Parse a per-TF config block. Only set fields that are explicitly present."""
    return AssetTimeframeConfig(
        interaction_tolerance_atr=raw.get("interaction_tolerance_atr"),
        asymmetry_threshold=raw.get("asymmetry_threshold"),
        convergence_rate_threshold=raw.get("convergence_rate_threshold"),
        wick_rejection_ratio=raw.get("wick_rejection_ratio"),
        squeeze_threshold=raw.get("squeeze_threshold"),
        history=(
            SnapshotHistoryOverride.from_mapping(raw["history"])
            if "history" in raw
            else None
        ),
    )


def _parse_assets(raw: Dict[str, Any]) -> Dict[str, AssetConfig]:
    """Parse the assets: block into typed AssetConfig objects."""
    assets: Dict[str, AssetConfig] = {}
    for asset_name, asset_raw in raw.items():
        if not isinstance(asset_raw, dict):
            continue
        metadata = dict(asset_raw.get("metadata", {}))
        tfs_raw = asset_raw.get("timeframes", {})
        timeframes: Dict[str, AssetTimeframeConfig] = {}
        if isinstance(tfs_raw, dict):
            for tf_name, tf_raw in tfs_raw.items():
                if isinstance(tf_raw, dict):
                    timeframes[str(tf_name)] = _parse_asset_tf_config(tf_raw)
        assets[str(asset_name)] = AssetConfig(metadata=metadata, timeframes=timeframes)
    return assets


def _parse_oscillator_defaults(raw: Dict[str, Any]) -> OscillatorDefaults:
    """Parse the oscillator_defaults: block."""
    return OscillatorDefaults(
        lookback_bars=int(raw.get("lookback_bars", 80)),
        extractor=str(raw.get("extractor", "fractal")),
        fitter=str(raw.get("fitter", "least_squares")),
        extractor_params=dict(raw.get("extractor_params", {"window_left": 5, "window_right": 5})),
        fitter_params=dict(raw.get("fitter_params", {"pivot_window": 2})),
        interaction_tolerance_atr=float(raw.get("interaction_tolerance_atr", 1.0)),
        atr_window=int(raw.get("atr_window", 14)),
    )


def _parse_oscillator_overrides(raw: Dict[str, Any]) -> Dict[str, OscillatorOverride]:
    """Parse the oscillator_overrides: block into typed OscillatorOverride objects."""
    overrides: Dict[str, OscillatorOverride] = {}
    for osc_name, osc_raw in raw.items():
        if not isinstance(osc_raw, dict):
            continue
        overrides[str(osc_name).lower()] = OscillatorOverride(
            is_bounded=bool(osc_raw.get("is_bounded", False)),
            value_range_lo=float(osc_raw["value_range_lo"]) if "value_range_lo" in osc_raw else None,
            value_range_hi=float(osc_raw["value_range_hi"]) if "value_range_hi" in osc_raw else None,
            lookback_bars=int(osc_raw["lookback_bars"]) if "lookback_bars" in osc_raw else None,
            extractor=str(osc_raw["extractor"]) if "extractor" in osc_raw else None,
            fitter=str(osc_raw["fitter"]) if "fitter" in osc_raw else None,
            extractor_params=dict(osc_raw["extractor_params"]) if "extractor_params" in osc_raw else None,
            fitter_params=dict(osc_raw["fitter_params"]) if "fitter_params" in osc_raw else None,
            interaction_tolerance_atr=float(osc_raw["interaction_tolerance_atr"]) if "interaction_tolerance_atr" in osc_raw else None,
            atr_window=int(osc_raw["atr_window"]) if "atr_window" in osc_raw else None,
        )
    return overrides


def load_trendlines_config(path: str | None = None) -> TrendlinesConfig:
    import pathlib

    if path is None:
        path = str(pathlib.Path(__file__).parent / "trendlines.yaml")

    raw = get_default_config_dict()
    if os.path.exists(path):
        with open(path, "r") as f:
            yaml_content = yaml.safe_load(f)
            if yaml_content:
                raw = _merge_dicts(raw, yaml_content)

    # ── Pipeline ──
    pipe_raw = raw.get("pipeline", {})

    history = (
        SnapshotHistoryPolicy.from_mapping(raw["history"])
        if "history" in raw
        else None
    )

    # ── Optimizable defaults ──
    def_raw = raw.get("defaults", {})
    defaults = OptimizableDefaults(
        interaction_tolerance_atr=float(def_raw.get("interaction_tolerance_atr", 0.25)),
        asymmetry_threshold=float(def_raw.get("asymmetry_threshold", 0.3)),
        convergence_rate_threshold=float(def_raw.get("convergence_rate_threshold", 0.2)),
        wick_rejection_ratio=float(def_raw.get("wick_rejection_ratio", 0.5)),
        squeeze_threshold=float(def_raw.get("squeeze_threshold", 3.0)),
    )

    # ── Per-asset configs ──
    assets = _parse_assets(raw.get("assets", {}))

    # ── Oscillator config ──
    osc_defaults = _parse_oscillator_defaults(raw.get("oscillator_defaults", {}))
    osc_overrides = _parse_oscillator_overrides(raw.get("oscillator_overrides", {}))

    # ── Signal weights ──
    sw_raw = raw.get("signal_weights", {})
    signal_default_weight = float(sw_raw.get("default_weight", 1.0))
    signal_weights = {
        str(k): float(v) for k, v in dict(sw_raw.get("weights", {})).items()
    }

    # ── Protocol (evaluation) ──
    proto_raw = raw.get("protocol", raw.get("evaluation", {}))
    fit_raw = proto_raw.get("fitness", {})
    wf_raw = proto_raw.get("walk_forward", {})
    lk_raw = proto_raw.get("lookback_grid", {})
    dm_raw = proto_raw.get("drift_monitor", {})

    protocol = EvaluationConfig(
        fitness=FitnessConfig(**fit_raw),
        walk_forward=WalkForwardDefaults(**wf_raw),
        lookback_grid=LookbackGridConfig(
            fractions=tuple(lk_raw.get("fractions", [0.4, 0.6, 0.8])),
            min_bars=lk_raw.get("min_bars", 20),
        ),
        drift_monitor=DriftMonitorConfig(**dm_raw),
    )

    # ── Search grids ──
    grids_raw = raw.get("search_grids", {})
    f_raw = grids_raw.get("fractal", {})
    rdp_raw = grids_raw.get("rdp_zigzag", {})
    path_raw = grids_raw.get("pathfinding", {})
    ls_raw = grids_raw.get("least_squares", {})
    rans_raw = grids_raw.get("ransac", {})

    search_grids = GridSearchConfig(
        fractal=FractalSearchGrid(
            left_windows=tuple(f_raw.get("left_windows", [3, 5, 7, 10])),
            right_windows=tuple(f_raw.get("right_windows", [3, 5, 7, 10])),
        ),
        rdp_zigzag=RDPSearchGrid(
            epsilon_atr_values=tuple(rdp_raw.get("epsilon_atr_values", [0.2, 0.3, 0.5, 0.8, 1.0])),
            min_segment_bars_values=tuple(rdp_raw.get("min_segment_bars_values", [1, 3, 5])),
        ),
        pathfinding=PathfindingSearchGrid(
            pivot_windows=tuple(path_raw.get("pivot_windows", [2, 3, 5])),
        ),
        least_squares=LeastSquaresSearchGrid(
            pivot_windows=tuple(ls_raw.get("pivot_windows", [2, 3, 5])),
            residual_thresholds=tuple(ls_raw.get("residual_thresholds", [0.3, 0.5, 0.8])),
        ),
        ransac=RansacSearchGrid(
            pivot_windows=tuple(rans_raw.get("pivot_windows", [2, 3])),
            residual_thresholds=tuple(rans_raw.get("residual_thresholds", [0.3, 0.5])),
            max_cut_fractions=tuple(rans_raw.get("max_cut_fractions", [0.1, 0.2])),
        ),
    )

    return TrendlinesConfig(
        extractor=str(pipe_raw.get("extractor", "fractal")),
        fitter=str(pipe_raw.get("fitter", "pathfinding")),
        defaults=defaults,
        assets=assets,
        oscillator_defaults=osc_defaults,
        oscillator_overrides=osc_overrides,
        protocol=protocol,
        search_grids=search_grids,
        signal_default_weight=signal_default_weight,
        signal_weights=signal_weights,
        history=history,
    )
