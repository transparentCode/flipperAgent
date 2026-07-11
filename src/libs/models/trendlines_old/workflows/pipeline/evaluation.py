"""Trendlines pipeline evaluation, walk-forward scoring, and parameter search."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.trendlines import TrendlineFitResult, TrendlinePipelineConfig, build_extractor, run_trendline_pipeline_from_config
from app.trendlines.contracts import Trendline
from app.trendlines.registry import get_extractor_search_grid, get_fitter_search_grid
from app.trendlines.data import TemporalSplitManifest
from app.trendlines.config import EvaluationConfig
from app.trendlines.workflows.pipeline.temporal_spec import (
    _manifest_windows,
    _trendline_lookback_grid,
    generate_windows,
    resolve_trendlines_workflow_config,
)
from app.trendlines.workflows.pipeline.support import _merge_param_dicts

_cfg = EvaluationConfig().fitness
_TOUCH_ACCURACY_FLOOR = 0.01


def _resolve_fit_frame(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    lookback_bars = params.get("lookback_bars")
    if lookback_bars is None:
        return df
    return df.tail(max(int(lookback_bars), 1)).copy()


def run_pipeline_with_params(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    params: Dict[str, Any],
) -> TrendlineFitResult:
    del asset, timeframe
    fit_df = _resolve_fit_frame(df, params)
    config = resolve_trendlines_workflow_config(params) or TrendlinePipelineConfig()
    return run_trendline_pipeline_from_config(fit_df, config)


def _fit_window_bars(train_df: pd.DataFrame, params: Dict[str, Any]) -> int:
    lookback_bars = params.get("lookback_bars")
    if lookback_bars is None:
        return len(train_df)
    return min(len(train_df), max(int(lookback_bars), 1))


def evaluate_trendlines_on_forward(
    lines: List[Trendline],
    test_df: pd.DataFrame,
    *,
    fit_window_bars: int,
) -> Dict[str, float]:
    if not lines or test_df.empty:
        return {
            "longevity": 0.0,
            "penetration_rate": 1.0,
            "touch_accuracy": 0.0,
            "fitness": 0.0,
            "n_lines": 0,
        }

    closes = test_df["close"].to_numpy(dtype=float)
    highs = test_df["high"].to_numpy(dtype=float)
    lows = test_df["low"].to_numpy(dtype=float)
    n_test = len(closes)
    test_x = np.arange(fit_window_bars, fit_window_bars + n_test, dtype=float)

    longevities = []
    pen_counts = []
    touch_hits = []
    touch_totals = []

    for line in lines:
        projected = line.slope * test_x + line.intercept
        from app.trendlines.optimization.benchmarks._tolerance import compute_tolerance
        tolerance = compute_tolerance(
            line.slope, test_df,
            slope_tolerance=_cfg.slope_tolerance,
            min_tolerance_atr_frac=_cfg.min_tolerance_atr_frac,
        )

        if line.is_support:
            penetrated = closes < (projected - tolerance)
            near = np.abs(lows - projected) < tolerance
        else:
            penetrated = closes > (projected + tolerance)
            near = np.abs(highs - projected) < tolerance

        life = n_test
        consecutive = 0
        for index in range(n_test):
            if penetrated[index]:
                consecutive += 1
                if consecutive >= _cfg.consecutive_penetration_bars:
                    life = index - (_cfg.consecutive_penetration_bars - 1)
                    break
            else:
                consecutive = 0
        longevities.append(max(life / n_test, 0.0))

        life_bars = max(life, 1)
        pen_counts.append(float(np.sum(penetrated[:life_bars])) / life_bars)

        touch_indices = np.where(near)[0]
        n_good = 0
        for touch_index in touch_indices:
            if touch_index + _cfg.forward_lookahead_bars >= n_test:
                continue
            if line.is_support:
                if np.any(closes[touch_index + 1 : touch_index + 1 + _cfg.forward_lookahead_bars] > closes[touch_index]):
                    n_good += 1
            else:
                if np.any(closes[touch_index + 1 : touch_index + 1 + _cfg.forward_lookahead_bars] < closes[touch_index]):
                    n_good += 1
        touch_totals.append(len(touch_indices))
        touch_hits.append(n_good)

    mean_longevity = float(np.mean(longevities)) if longevities else 0.0
    mean_pen_rate = float(np.mean(pen_counts)) if pen_counts else 1.0
    total_touches = sum(touch_totals)
    total_hits = sum(touch_hits)
    touch_acc = total_hits / max(total_touches, 1)
    fitness = mean_longevity * (1.0 - mean_pen_rate) * max(touch_acc, _TOUCH_ACCURACY_FLOOR)

    return {
        "longevity": round(mean_longevity, 4),
        "penetration_rate": round(mean_pen_rate, 4),
        "touch_accuracy": round(touch_acc, 4),
        "fitness": round(fitness, 6),
        "n_lines": len(lines),
    }


def walk_forward_evaluate(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    params: Dict[str, Any],
    train_bars: int,
    test_bars: int,
    step_bars: Optional[int] = None,
    manifest: Optional[TemporalSplitManifest] = None,
) -> Dict[str, Any]:
    windows = (
        _manifest_windows(manifest)
        if manifest is not None
        else generate_windows(len(df), train_bars, test_bars, step_bars)
    )
    if not windows:
        return {"mean_fitness": 0.0, "std_fitness": 0.0, "n_windows": 0, "window_scores": []}

    window_scores = []
    for train_s, train_e, test_s, test_e in windows:
        train_df = df.iloc[train_s:train_e]
        test_df = df.iloc[test_s:test_e]
        result = run_pipeline_with_params(train_df, asset, timeframe, params)

        if not result.is_valid:
            window_scores.append(0.0)
            continue

        fit_bars = _fit_window_bars(train_df, params)
        lines = result.support_lines + result.resistance_lines
        metrics = evaluate_trendlines_on_forward(lines, test_df, fit_window_bars=fit_bars)
        window_scores.append(metrics["fitness"])

    scores = np.array(window_scores)
    return {
        "mean_fitness": round(float(np.mean(scores)), 6),
        "std_fitness": round(float(np.std(scores)), 6),
        "n_windows": len(windows),
        "window_scores": [round(score, 6) for score in window_scores],
    }


def evaluate_pivot_count(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    params: Dict[str, Any],
    train_bars: int,
    test_bars: int,
    step_bars: Optional[int] = None,
    manifest: Optional[TemporalSplitManifest] = None,
) -> Dict[str, Any]:
    del asset, timeframe
    windows = (
        _manifest_windows(manifest)
        if manifest is not None
        else generate_windows(len(df), train_bars, test_bars, step_bars)
    )
    if not windows:
        return {"mean_pivots": 0.0, "std_pivots": 0.0, "n_windows": 0}

    pivot_counts = []
    for train_s, train_e, _, _ in windows:
        train_df = _resolve_fit_frame(df.iloc[train_s:train_e], params)
        config = resolve_trendlines_workflow_config(params) or TrendlinePipelineConfig()
        extractor = build_extractor(config.extractor, **config.extractor_params)
        pivots = extractor.extract(train_df)
        pivot_counts.append(pivots.n_highs + pivots.n_lows)

    counts = np.array(pivot_counts)
    return {
        "mean_pivots": round(float(np.mean(counts)), 1),
        "std_pivots": round(float(np.std(counts)), 1),
        "n_windows": len(windows),
    }


def _extractor_grid(extractor_name: str) -> List[Dict[str, Any]]:
    return get_extractor_search_grid(extractor_name)


def _trendline_fitter_grid() -> List[Dict[str, Any]]:
    return get_fitter_search_grid()


def search_pipeline_parameters(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    extractor_name: str,
    manifest: TemporalSplitManifest,
    *,
    quiet: bool = False,
) -> Dict[str, Any]:
    started = datetime.now(timezone.utc).isoformat()

    def _log(message: str) -> None:
        if not quiet:
            print(message)

    train_bars = manifest.spec.train_bars
    test_bars = manifest.spec.test_bars
    step_bars = manifest.spec.step_bars

    _log(f"\n  [Step 1/3] Sweeping {extractor_name} trendlines extractor params...")
    ext_grid = _extractor_grid(extractor_name)
    ext_scores = []

    for index, ext_params in enumerate(ext_grid):
        pcount = evaluate_pivot_count(
            df,
            asset,
            timeframe,
            ext_params,
            train_bars,
            test_bars,
            step_bars,
            manifest=manifest,
        )
        mean_piv = pcount["mean_pivots"]
        std_piv = pcount["std_pivots"]
        # Density-based scoring: pivots per 100 bars
        density = (mean_piv / max(train_bars, 1)) * 100
        if density < _cfg.pivot_density_min:
            pivot_score = 0.0
        elif density < _cfg.pivot_density_optimal_lo:
            pivot_score = (density - _cfg.pivot_density_min) / max(_cfg.pivot_density_optimal_lo - _cfg.pivot_density_min, 1e-9)
        elif density <= _cfg.pivot_density_optimal_hi:
            pivot_score = 1.0
        else:
            pivot_score = max(0.0, 1.0 - (density - _cfg.pivot_density_optimal_hi) / max(_cfg.pivot_density_optimal_hi, 1e-9))
        stability = 1.0 / (1.0 + std_piv / max(mean_piv, 1.0))
        combined = pivot_score * stability
        ext_scores.append(
            {
                "params": ext_params,
                "mean_pivots": mean_piv,
                "std_pivots": std_piv,
                "pivot_score": round(pivot_score, 4),
                "stability": round(stability, 4),
                "combined": round(combined, 4),
            }
        )
        _log(
            f"    [{index+1}/{len(ext_grid)}] pivots={mean_piv:.0f} ± {std_piv:.1f}  score={combined:.3f}"
        )

    ext_scores.sort(key=lambda item: item["combined"], reverse=True)
    best_ext = ext_scores[0]["params"]
    _log(f"  Best extractor: {best_ext}  (pivots={ext_scores[0]['mean_pivots']:.0f})")

    _log("\n  [Step 2/3] Sweeping trendlines fitter params...")
    fitter_grid = _trendline_fitter_grid()
    fitter_scores = []

    for index, fitter_params in enumerate(fitter_grid):
        merged = _merge_param_dicts(best_ext, fitter_params)
        wf = walk_forward_evaluate(
            df,
            asset,
            timeframe,
            merged,
            train_bars,
            test_bars,
            step_bars,
            manifest=manifest,
        )
        fitter_scores.append(
            {
                "params": fitter_params,
                "mean_fitness": wf["mean_fitness"],
                "std_fitness": wf["std_fitness"],
                "n_windows": wf["n_windows"],
            }
        )
        _log(
            f"    [{index+1}/{len(fitter_grid)}] F={wf['mean_fitness']:.4f} ± {wf['std_fitness']:.4f}"
        )

    fitter_scores.sort(key=lambda item: item["mean_fitness"], reverse=True)
    best_fitter = fitter_scores[0]["params"]
    _log(f"  Best fitter: {best_fitter}  (F={fitter_scores[0]['mean_fitness']:.4f})")

    _log("\n  [Step 3/3] Sweeping trendlines lookback...")
    lookback_grid = _trendline_lookback_grid(train_bars)
    lookback_scores = []

    for index, lookback_params in enumerate(lookback_grid):
        merged = _merge_param_dicts(best_ext, best_fitter, lookback_params)
        wf = walk_forward_evaluate(
            df,
            asset,
            timeframe,
            merged,
            train_bars,
            test_bars,
            step_bars,
            manifest=manifest,
        )

        sample_result = run_pipeline_with_params(df, asset, timeframe, merged)
        total_lines = len(sample_result.support_lines) + len(sample_result.resistance_lines)
        if total_lines == 0:
            line_count_penalty = _cfg.line_count_penalty_factor
        elif total_lines > _cfg.line_count_penalty_threshold:
            line_count_penalty = max(0.3, 1.0 - (total_lines - _cfg.line_count_penalty_threshold) * _cfg.line_count_penalty_factor)
        else:
            line_count_penalty = 1.0

        adjusted_fitness = wf["mean_fitness"] * line_count_penalty
        lookback_scores.append(
            {
                "params": lookback_params,
                "mean_fitness": wf["mean_fitness"],
                "adjusted_fitness": round(adjusted_fitness, 6),
                "std_fitness": wf["std_fitness"],
                "n_support": len(sample_result.support_lines),
                "n_resistance": len(sample_result.resistance_lines),
            }
        )
        _log(
            f"    [{index+1}/{len(lookback_grid)}] F={adjusted_fitness:.4f}  lines=S{len(sample_result.support_lines)}/R{len(sample_result.resistance_lines)}"
        )

    lookback_scores.sort(key=lambda item: item["adjusted_fitness"], reverse=True)
    best_lookback = lookback_scores[0]["params"]
    _log(f"  Best lookback: {best_lookback}  (F={lookback_scores[0]['adjusted_fitness']:.4f})")

    best_params = _merge_param_dicts(best_ext, best_fitter, best_lookback)
    final_wf = walk_forward_evaluate(
        df,
        asset,
        timeframe,
        best_params,
        train_bars,
        test_bars,
        step_bars,
        manifest=manifest,
    )

    completed = datetime.now(timezone.utc).isoformat()
    return {
        "engine": "trendlines",
        "asset": asset,
        "timeframe": timeframe,
        "started_at": started,
        "completed_at": completed,
        "best_params": best_params,
        "best_fitness": final_wf["mean_fitness"],
        "best_fitness_std": final_wf["std_fitness"],
        "n_windows": final_wf["n_windows"],
        "window_scores": final_wf["window_scores"],
        "step_results": {
            "step1_extractor": {"best": ext_scores[0], "grid_size": len(ext_scores)},
            "step2_fitter": {"best": fitter_scores[0], "grid_size": len(fitter_scores)},
            "step3_lookback": {"best": lookback_scores[0], "grid_size": len(lookback_scores)},
        },
    }


__all__ = [
    "evaluate_pivot_count",
    "evaluate_trendlines_on_forward",
    "run_pipeline_with_params",
    "search_pipeline_parameters",
    "walk_forward_evaluate",
]
