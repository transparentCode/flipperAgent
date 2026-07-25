"""
Trendlines Hyperparameter Optimization Script.

Fetches OHLCV data from Binance Futures and runs Bayesian optimization
over 5 continuous + 3 categorical trendline params per asset/timeframe
with walk-forward CV and 5-tier geometric objective.

Usage
-----
# Single asset
python app/trendlines/scripts/run_optimization.py \
    --asset BTCUSDT --timeframe 1h \
    --n-trials 50 --timeout 1800

# Multiple assets
python app/trendlines/scripts/run_optimization.py \
    --assets BTCUSDT ETHUSDT SOLUSDT \
    --timeframe 1h --n-trials 50

# Staged (2-stage: fix categoricals first, then joint)
python app/trendlines/scripts/run_optimization.py \
    --asset BTCUSDT --timeframe 1h \
    --staged --stage1-trials 30 --stage2-trials 50

# Universe mode (batch from YAML)
python app/trendlines/scripts/run_optimization.py \
    --universe universe.yaml --n-trials 50

# From CSV (offline)
python app/trendlines/scripts/run_optimization.py \
    --asset BTCUSDT --timeframe 1h --csv data/btc_1h.csv

# With monitoring (separate terminal)
python app/trendlines/scripts/monitor_optimization.py \
    --status-file app/trendlines/optimization/results/.optimization_status.json

Output
------
- Results JSON saved to app/trendlines/optimization/results/
- Best params written to app/trendlines/config/trendlines.yaml
- Status file at .optimization_status.json (for monitoring)
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import platform
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

# Ensure project root is on path
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import yaml

from app.trendlines.optimization import (
    TrendlinesOptimizationConfig,
    TrendlinesOptimizer,
)
from app.trendlines.optimization.models import TrendlinesOptimizationResult
from app.trendlines.optimization.oscillator import (
    OscillatorOptimizationConfig,
    apply_oscillator_result,
    optimize_oscillator_trendlines,
)

logger = logging.getLogger("app.trendlines.optimization")


# ---------------------------------------------------------------------------
# Status file writer (contract with monitor_optimization.py)
# ---------------------------------------------------------------------------

class StatusFileWriter:
    """Writes atomic JSON status file for the optimization monitor."""

    def __init__(self, output_dir: Path, asset: str, timeframe: str):
        self.status_path = output_dir / ".optimization_status.json"
        self._base = {
            "pid": os.getpid(),
            "asset": asset,
            "timeframe": timeframe,
            "start_time": datetime.now().isoformat(),
            "module": "trendlines",
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        if self.status_path.exists():
            self.status_path.unlink()
        self._write(status="starting", trial_current=0, trial_total=0,
                     best_score=0.0, best_params={}, stage="init",
                     stage_name="Initializing", errors=[], metrics_summary={})
        logger.info("Status file: %s", self.status_path.resolve())

    def update(self, *, trial_current: int, trial_total: int,
               best_score: float, best_params: dict,
               stage: str, stage_name: str, **extra) -> None:
        self._write(status="running", trial_current=trial_current,
                     trial_total=trial_total, best_score=best_score,
                     best_params=best_params, stage=stage,
                     stage_name=stage_name, errors=[], metrics_summary={},
                     **extra)

    def complete(self, result: TrendlinesOptimizationResult) -> None:
        self._write(status="completed",
                     trial_current=result.n_trials_total,
                     trial_total=result.n_trials_total,
                     best_score=result.best_objective,
                     best_params=result.best_params,
                     stage="done", stage_name="Completed",
                     errors=[], metrics_summary=result.best_benchmarks.to_dict())

    def fail(self, error_msg: str) -> None:
        self._write(status="failed", trial_current=0, trial_total=0,
                     best_score=0.0, best_params={}, stage="error",
                     stage_name="Failed", errors=[error_msg], metrics_summary={})

    def _write(self, **fields) -> None:
        data = {**self._base, "last_update": datetime.now().isoformat(), **fields}
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=self.status_path.parent, suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp_path, self.status_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Data fetching with caching
# ---------------------------------------------------------------------------

def fetch_data(
    asset: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    cache_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """Fetch paginated OHLCV data from Binance Futures, with optional caching."""
    if cache_dir is not None:
        cache_path = cache_dir / f"{asset}_{timeframe}_{start_date}_{end_date}.csv"
        if cache_path.exists():
            logger.info("Loading cached data from %s", cache_path)
            df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
            logger.info("Loaded %d bars from cache", len(df))
            return df

    from app.connectors.BinanceConnector import BinanceConnector
    connector = BinanceConnector()

    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    current_start = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)

    logger.info("Fetching %s %s (%s to %s) from Binance...",
                asset, timeframe, start_date, end_date)

    all_chunks: List[pd.DataFrame] = []
    while current_start < end_ts:
        try:
            chunk = connector.get_futures_klines(
                symbol=asset, interval=timeframe,
                start_time=current_start, end_time=end_ts, limit=1000,
            )
            if chunk.empty:
                break
            all_chunks.append(chunk)
            last_close_ts = int(chunk["close_time"].iloc[-1].timestamp() * 1000)
            next_start = last_close_ts + 1
            if next_start <= current_start:
                break
            current_start = next_start
            time.sleep(0.1)
        except Exception as e:
            logger.error("Error fetching chunk: %s", e)
            break

    if not all_chunks:
        raise ValueError(f"No data fetched for {asset}")

    df = pd.concat(all_chunks)
    df = df[~df.index.duplicated(keep="first")]
    df = df[(df.index >= start_dt) & (df.index <= end_dt)]
    df.sort_index(inplace=True)

    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{asset}_{timeframe}_{start_date}_{end_date}.csv"
        df.to_csv(cache_path)
        logger.info("Cached %d bars to %s", len(df), cache_path)

    logger.info("Fetched %d bars for %s %s", len(df), asset, timeframe)
    return df


def load_data_from_csv(path: str) -> pd.DataFrame:
    """Load OHLCV data from a CSV file."""
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing columns: {missing}")
    return df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _backup_yaml(yaml_path: str) -> None:
    p = Path(yaml_path)
    if p.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = p.with_name(f"{p.name}.bak.{ts}")
        shutil.copy2(p, backup)
        logger.info("Backed up %s -> %s", p.name, backup.name)


def _make_status_callback(
    status_writer: Optional[StatusFileWriter],
    n_total: int, stage: str, stage_name: str,
):
    if status_writer is None:
        return None

    def callback(study, trial):
        best_score = study.best_value if len(study.trials) > 0 else 0.0
        best_params = study.best_params if len(study.trials) > 0 else {}
        status_writer.update(
            trial_current=trial.number + 1,
            trial_total=n_total,
            best_score=best_score,
            best_params=best_params,
            stage=stage,
            stage_name=stage_name,
        )

    return callback


def _plateau_analysis(result: TrendlinesOptimizationResult, label: str) -> bool:
    """Check if optimization converged. Returns True if converged."""
    trials = result.all_trials
    if len(trials) < 10:
        return False

    scores = [t.objective_value for t in trials]
    n = len(scores)
    best_so_far = np.maximum.accumulate(scores)

    tail_start = max(0, int(n * 0.8))
    tail_improvement = best_so_far[-1] - best_so_far[tail_start]

    top_n = max(3, n // 10)
    top_scores = sorted(scores, reverse=True)[:top_n]
    cv = np.std(top_scores) / (np.mean(top_scores) + 1e-10)

    plateau = tail_improvement < 0.005 and cv < 0.10

    logger.info("[%s] Plateau: tail_improvement=%.4f, top-10%% CV=%.4f -> %s",
                label, tail_improvement, cv,
                "CONVERGED" if plateau else "NOT YET")
    return plateau


def _print_comparison(
    yaml_path: str, new_params: Dict[str, Any],
    asset: str, timeframe: str,
) -> None:
    try:
        with open(yaml_path) as f:
            raw = yaml.safe_load(f) or {}
        old_params = raw.get("assets", {}).get(asset, {}).get("timeframes", {}).get(timeframe, {})
    except Exception:
        old_params = {}

    if not old_params:
        logger.info("No existing params for %s %s — fresh write", asset, timeframe)
        return

    print(f"\n  {'Param':<35} {'Old':>12}  {'New':>12}  {'Delta':>10}")
    print(f"  {'-'*73}")
    for k, new_v in sorted(new_params.items()):
        old_v = old_params.get(k)
        if old_v is not None and isinstance(old_v, (int, float)) and isinstance(new_v, (int, float)):
            delta = f"{new_v - old_v:+.4f}"
        else:
            delta = "new"
        old_str = f"{old_v:.4f}" if isinstance(old_v, float) else str(old_v or "—")
        new_str = f"{new_v:.4f}" if isinstance(new_v, float) else str(new_v)
        print(f"  {k:<35} {old_str:>12}  {new_str:>12}  {delta:>10}")


def _print_full_metrics(result: TrendlinesOptimizationResult) -> None:
    b = result.best_benchmarks
    divider = "=" * 70
    thin = "-" * 55

    print(f"\n{divider}")
    print(f"  {result.asset} {result.timeframe} -- Full Metrics")
    print(f"{divider}")
    print(f"  Objective:                  {result.best_objective:.4f}")
    print(f"  Trials passed gate:         {result.n_trials_passed_gate}/{result.n_trials_total}")
    print(f"  Time:                       {result.total_time_seconds:.1f}s")

    print(f"\n  Tier 1 -- Longevity (35%)")
    print(f"  {thin}")
    print(f"    Mean longevity:           {b.mean_longevity:.4f}")
    print(f"    N lines:                  {b.n_lines:.0f}")

    print(f"\n  Tier 2 -- Touch Accuracy (25%)")
    print(f"  {thin}")
    print(f"    Touch accuracy:           {b.touch_accuracy:.4f}")
    print(f"    Total touches:            {b.total_touches:.0f}")
    print(f"    Total hits:               {b.total_hits:.0f}")

    print(f"\n  Tier 3 -- Penetration Rate (GATE)")
    print(f"  {thin}")
    print(f"    Mean pen rate:            {b.mean_pen_rate:.4f}  (lower=better)")
    print(f"    Gate status:              {'PASS' if b.passed_penetration_gate else 'FAIL'}")

    print(f"\n  Tier 4 -- Pivot Density (CONSTRAINT)")
    print(f"  {thin}")
    print(f"    Mean pivots:              {b.mean_pivots:.1f}")
    print(f"    Density (per 100 bars):   {b.pivot_density:.1f}")
    print(f"    Pivot score:              {b.pivot_score:.4f}")
    print(f"    Constraint status:        {'PASS' if b.passed_pivot_constraint else 'FAIL'}")

    print(f"\n  Tier 5 -- Fold Stability (15%)")
    print(f"  {thin}")
    print(f"    Fitness CV:               {b.fitness_cv:.4f}  (lower=better)")
    print(f"    Stability score:          {b.stability_score:.4f}")

    print(f"\n  Composite")
    print(f"  {thin}")
    print(f"    Raw fitness:              {b.fitness:.6f}")
    print(f"    N folds:                  {b.n_folds:.0f}")
    print(f"    N bars:                   {b.n_bars:.0f}")

    print(f"\n{divider}\n")


def _print_summary(result: TrendlinesOptimizationResult) -> None:
    b = result.best_benchmarks
    print(f"\n{'='*60}")
    print(f"  {result.asset} {result.timeframe} -- Optimization Complete")
    print(f"{'='*60}")
    print(f"  Best objective:       {result.best_objective:.4f}")
    print(f"  Trials passed gate:   {result.n_trials_passed_gate}/{result.n_trials_total}")
    print(f"  Time:                 {result.total_time_seconds:.1f}s")
    print(f"  Best params:")
    for k, v in sorted(result.best_params.items()):
        if isinstance(v, float):
            print(f"    {k:35s} = {v:.6f}")
        else:
            print(f"    {k:35s} = {v}")
    print(f"  Key metrics:")
    print(f"    Longevity:           {b.mean_longevity:.3f}")
    print(f"    Touch accuracy:      {b.touch_accuracy:.3f}")
    print(f"    Pen rate:            {b.mean_pen_rate:.3f}  "
          f"({'PASS' if b.passed_penetration_gate else 'FAIL'})")
    print(f"    Pivot score:         {b.pivot_score:.3f}")
    print(f"    Stability:           {b.stability_score:.3f}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Optimization runners
# ---------------------------------------------------------------------------

def run_single(
    asset: str,
    timeframe: str,
    df: pd.DataFrame,
    config: TrendlinesOptimizationConfig,
    output_dir: Path,
    config_yaml: str,
    apply_results: bool = True,
    status_writer: Optional[StatusFileWriter] = None,
    full_metrics: bool = True,
) -> TrendlinesOptimizationResult:
    """Run single optimization and save results."""
    logger.info("=== Optimizing %s %s ===", asset, timeframe)

    cb = _make_status_callback(status_writer, config.n_trials, "single", "Full optimization")
    optimizer = TrendlinesOptimizer(config)
    result = optimizer.optimize(
        df, asset=asset, timeframe=timeframe,
        callbacks=[cb] if cb else None,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_path = output_dir / f"{asset}_{timeframe}_{ts}.json"
    result.save(str(out_path))
    logger.info("Saved result to %s", out_path)

    if apply_results:
        if Path(config_yaml).exists():
            _print_comparison(config_yaml, result.best_params, asset, timeframe)
            _backup_yaml(config_yaml)
        result.apply_to_config(config_yaml)
        logger.info("Applied params to %s", config_yaml)

    _print_summary(result)
    _plateau_analysis(result, f"{asset} {timeframe}")

    if full_metrics:
        _print_full_metrics(result)

    if status_writer:
        status_writer.complete(result)

    return result


def run_staged(
    asset: str,
    timeframe: str,
    df: pd.DataFrame,
    stage1_trials: int,
    stage2_trials: int,
    base_config: TrendlinesOptimizationConfig,
    output_dir: Path,
    config_yaml: str,
    apply_results: bool = True,
    status_writer: Optional[StatusFileWriter] = None,
    plateau_stop: bool = False,
    full_metrics: bool = True,
) -> TrendlinesOptimizationResult:
    """2-stage hierarchical optimization.

    Stage 1: Fix categorical params (extractor/fitter grids) at midpoint,
             optimize only the 5 continuous params.
    Stage 2: Joint optimization — all 8 params free, continuous params
             narrowed ±20% around Stage 1 best.
    """
    logger.info("=== Staged optimization: %s %s ===", asset, timeframe)

    # ------------------------------------------------------------------
    # Stage 1: Continuous params only — categoricals pinned at midpoint
    # ------------------------------------------------------------------
    logger.info("--- Stage 1: Continuous params (%d trials) ---", stage1_trials)

    # Pin categoricals to middle value
    mid_left = base_config.extractor_left_windows[len(base_config.extractor_left_windows) // 2]
    mid_right = base_config.extractor_right_windows[len(base_config.extractor_right_windows) // 2]
    mid_pivot = base_config.fitter_pivot_windows[len(base_config.fitter_pivot_windows) // 2]

    s1_config = dataclasses.replace(
        base_config,
        n_trials=stage1_trials,
        timeout_seconds=base_config.timeout_seconds // 2,
        extractor_left_windows=(mid_left,),
        extractor_right_windows=(mid_right,),
        fitter_pivot_windows=(mid_pivot,),
    )
    cb1 = _make_status_callback(status_writer, stage1_trials, "stage1", "Continuous params")
    r1 = TrendlinesOptimizer(s1_config).optimize(
        df, asset=asset, timeframe=timeframe,
        n_trials=stage1_trials, callbacks=[cb1] if cb1 else None,
    )
    _print_summary(r1)
    s1_converged = _plateau_analysis(r1, "Stage 1 (Continuous)")

    # ------------------------------------------------------------------
    # Stage 2: Joint optimization — narrow continuous around Stage 1 best
    # ------------------------------------------------------------------
    if plateau_stop and s1_converged:
        stage2_trials = max(10, stage2_trials // 2)
        logger.info("Plateau detected -- reducing Stage 2 to %d trials", stage2_trials)

    logger.info("--- Stage 2: Joint optimization (%d trials) ---", stage2_trials)

    def _narrow(val: float, full_range: tuple, factor: float = 0.2) -> tuple:
        lo, hi = full_range
        margin = (hi - lo) * factor
        return (max(lo, val - margin), min(hi, val + margin))

    bp = r1.best_params
    s2_config = dataclasses.replace(
        base_config,
        n_trials=stage2_trials,
        timeout_seconds=base_config.timeout_seconds // 2,
        interaction_tolerance_atr=_narrow(
            bp["interaction_tolerance_atr"],
            base_config.interaction_tolerance_atr,
        ),
        asymmetry_threshold=_narrow(
            bp["asymmetry_threshold"],
            base_config.asymmetry_threshold,
        ),
        convergence_rate_threshold=_narrow(
            bp["convergence_rate_threshold"],
            base_config.convergence_rate_threshold,
        ),
        wick_rejection_ratio=_narrow(
            bp["wick_rejection_ratio"],
            base_config.wick_rejection_ratio,
        ),
        squeeze_threshold=_narrow(
            bp["squeeze_threshold"],
            base_config.squeeze_threshold,
        ),
    )
    cb2 = _make_status_callback(status_writer, stage2_trials, "stage2", "Joint optimization")
    final = TrendlinesOptimizer(s2_config).optimize(
        df, asset=asset, timeframe=timeframe,
        n_trials=stage2_trials, callbacks=[cb2] if cb2 else None,
    )

    # Save and apply
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_path = output_dir / f"{asset}_{timeframe}_{ts}_staged.json"
    final.save(str(out_path))
    logger.info("Saved staged result to %s", out_path)

    if apply_results:
        if Path(config_yaml).exists():
            _print_comparison(config_yaml, final.best_params, asset, timeframe)
            _backup_yaml(config_yaml)
        final.apply_to_config(config_yaml)
        logger.info("Applied params to %s", config_yaml)

    _print_summary(final)
    _plateau_analysis(final, "Stage 2 (Joint)")

    if full_metrics:
        _print_full_metrics(final)

    if status_writer:
        status_writer.complete(final)

    return final


def run_oscillator(
    asset: str,
    timeframe: str,
    df: pd.DataFrame,
    oscillator_type: str,
    config: OscillatorOptimizationConfig,
    output_dir: Path,
    config_yaml: str,
    apply_results: bool = True,
    status_writer: Optional[StatusFileWriter] = None,
    full_metrics: bool = True,
) -> TrendlinesOptimizationResult:
    """Run oscillator trendline optimization.

    Fetches the oscillator series from price data, builds a synthetic OHLCV
    DataFrame, then optimizes trendline parameters in oscillator space.
    """
    logger.info(
        "=== Oscillator optimization: %s %s [%s] ===",
        asset, timeframe, oscillator_type,
    )

    # --- Compute oscillator series from price OHLCV ---
    from app.trendlines.config.oscillator_profile import OscillatorProfile

    osc_series = _compute_oscillator_series(df, oscillator_type)
    osc_df = _prepare_oscillator_df(osc_series, df.index)
    logger.info(
        "Oscillator DF: %d bars, range [%.2f, %.2f]",
        len(osc_df), osc_df["close"].min(), osc_df["close"].max(),
    )

    cb = _make_status_callback(
        status_writer, config.n_trials, "oscillator", f"{oscillator_type} optimization",
    )
    result = optimize_oscillator_trendlines(
        df=osc_df,
        asset=asset,
        timeframe=timeframe,
        oscillator_type=oscillator_type,
        config=config,
        callbacks=[cb] if cb else None,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_path = output_dir / f"{asset}_{timeframe}_{oscillator_type}_{ts}.json"
    result.save(str(out_path))
    logger.info("Saved oscillator result to %s", out_path)

    if apply_results:
        _backup_yaml(config_yaml)
        apply_oscillator_result(result, config_yaml, oscillator_type)
        logger.info("Applied oscillator params to %s", config_yaml)

    _print_summary(result)

    if full_metrics:
        _print_full_metrics(result)

    if status_writer:
        status_writer.complete(result)

    return result


def _compute_oscillator_series(df: pd.DataFrame, oscillator_type: str) -> pd.Series:
    """Compute oscillator from price OHLCV."""
    if oscillator_type == "rsi":
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        return (100 - 100 / (1 + rs)).dropna()
    elif oscillator_type == "macd":
        ema12 = df["close"].ewm(span=12, adjust=False).mean()
        ema26 = df["close"].ewm(span=26, adjust=False).mean()
        return (ema12 - ema26).dropna()
    else:
        raise ValueError(f"Unsupported oscillator type: {oscillator_type}")


def _prepare_oscillator_df(series: pd.Series, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Build synthetic OHLCV from oscillator series for the trendline pipeline."""
    s = series.reindex(index).dropna()
    return pd.DataFrame(
        {"open": s, "high": s, "low": s, "close": s, "volume": 1.0},
        index=s.index,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_config(args) -> TrendlinesOptimizationConfig:
    return TrendlinesOptimizationConfig(
        n_trials=args.n_trials,
        timeout_seconds=args.timeout,
        n_jobs=args.n_jobs,
        sampler=args.sampler,
        pruner=args.pruner,
        soft_gate=not args.hard_gate,
        train_bars=args.train_bars,
        test_bars=args.test_bars,
        step_bars=args.step_bars,
        purge_bars=args.purge_bars,
        min_train_bars=args.min_train_bars,
    )


def _load_universe(path: str) -> List[Dict[str, Any]]:
    with open(path) as f:
        data = yaml.safe_load(f)
    entries = data.get("assets", [])
    if not entries:
        raise ValueError(f"Universe file {path} has no assets defined")
    return entries


def main():
    parser = argparse.ArgumentParser(
        description="Trendlines hyperparameter optimization via Binance data",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Asset / timeframe
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--asset", type=str, help="Single asset (e.g. BTCUSDT)")
    group.add_argument("--assets", nargs="+", help="Multiple assets")
    group.add_argument("--universe", type=str,
                       help="YAML file with asset/timeframe universe")

    parser.add_argument("--timeframe", type=str, default="1h",
                        help="Timeframe (e.g. 1h, 4h)")

    # Data source
    parser.add_argument("--start-date", type=str, default="2023-01-01")
    parser.add_argument("--end-date", type=str, default="2026-03-01")
    parser.add_argument("--csv", type=str, default=None,
                        help="Load data from CSV instead of Binance")
    parser.add_argument("--cache-dir", type=str,
                        default="app/trendlines/optimization/results")

    # Optimization settings
    parser.add_argument("--n-trials", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=1800,
                        help="Timeout in seconds")
    parser.add_argument("--n-jobs", type=int, default=1)
    parser.add_argument("--sampler", type=str, default="tpe",
                        choices=["tpe", "random", "cmaes"])
    parser.add_argument("--pruner", type=str, default="median",
                        choices=["median", "hyperband", "none"])
    parser.add_argument("--hard-gate", action="store_true",
                        help="Hard-fail trials that don't pass penetration gate")

    # Oscillator mode
    parser.add_argument("--oscillator", type=str, default=None,
                        choices=["rsi", "macd"],
                        help="Optimize oscillator trendlines instead of price")

    # Walk-forward settings
    parser.add_argument("--train-bars", type=int, default=2160)
    parser.add_argument("--test-bars", type=int, default=720)
    parser.add_argument("--step-bars", type=int, default=720)
    parser.add_argument("--purge-bars", type=int, default=24)
    parser.add_argument("--min-train-bars", type=int, default=1440)

    # Staged optimization
    parser.add_argument("--staged", action="store_true",
                        help="Run 2-stage hierarchical optimization")
    parser.add_argument("--stage1-trials", type=int, default=30)
    parser.add_argument("--stage2-trials", type=int, default=50)
    parser.add_argument("--plateau-stop", action="store_true",
                        help="Auto-reduce Stage 2 budget on convergence")

    # Output
    parser.add_argument("--output-dir", type=str,
                        default="app/trendlines/optimization/results")
    parser.add_argument("--config-yaml", type=str,
                        default="app/trendlines/config/trendlines.yaml")
    parser.add_argument("--no-apply", action="store_true",
                        help="Skip writing to trendlines.yaml")
    parser.add_argument("--no-status", action="store_true")
    parser.add_argument("--no-full-metrics", action="store_true")

    # Logging
    parser.add_argument("--log-level", type=str, default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.n_jobs > 1 and platform.system() == "Darwin":
        logger.warning(
            "n_jobs=%d on macOS may deadlock due to BLAS thread oversubscription. "
            "Consider --n-jobs 1.", args.n_jobs,
        )

    # Build asset list
    if args.universe:
        universe = _load_universe(args.universe)
    elif args.asset:
        universe = [{"symbol": args.asset, "timeframe": args.timeframe}]
    else:
        universe = [{"symbol": a, "timeframe": args.timeframe} for a in args.assets]

    config = build_config(args)
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = _ROOT / output_dir
    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    if cache_dir and not cache_dir.is_absolute():
        cache_dir = _ROOT / cache_dir
    config_yaml = args.config_yaml
    if not Path(config_yaml).is_absolute():
        config_yaml = str(_ROOT / config_yaml)
    apply_results = not args.no_apply
    full_metrics = not args.no_full_metrics

    # Build oscillator config if in oscillator mode
    osc_config = None
    if args.oscillator:
        osc_config = OscillatorOptimizationConfig(
            n_trials=args.n_trials,
            timeout_seconds=args.timeout,
            n_jobs=args.n_jobs,
            sampler=args.sampler,
            pruner=args.pruner,
            soft_gate=not args.hard_gate,
        )

    for entry in universe:
        asset = entry["symbol"]
        timeframe = entry.get("timeframe", args.timeframe)
        start_date = entry.get("start_date", args.start_date)
        end_date = entry.get("end_date", args.end_date)

        status_writer = None
        if not args.no_status:
            status_writer = StatusFileWriter(output_dir, asset, timeframe)

        try:
            if args.csv:
                df = load_data_from_csv(args.csv)
            else:
                df = fetch_data(asset, timeframe, start_date, end_date,
                                cache_dir=cache_dir)

            min_bars = config.train_bars + config.test_bars
            if len(df) < min_bars:
                logger.warning(
                    "Not enough data for %s %s: got %d bars, need %d",
                    asset, timeframe, len(df), min_bars,
                )
                continue

            if args.oscillator:
                run_oscillator(
                    asset=asset, timeframe=timeframe, df=df,
                    oscillator_type=args.oscillator,
                    config=osc_config,
                    output_dir=output_dir, config_yaml=config_yaml,
                    apply_results=apply_results,
                    status_writer=status_writer,
                    full_metrics=full_metrics,
                )
            elif args.staged:
                run_staged(
                    asset=asset, timeframe=timeframe, df=df,
                    stage1_trials=args.stage1_trials,
                    stage2_trials=args.stage2_trials,
                    base_config=config,
                    output_dir=output_dir, config_yaml=config_yaml,
                    apply_results=apply_results,
                    status_writer=status_writer,
                    plateau_stop=args.plateau_stop,
                    full_metrics=full_metrics,
                )
            else:
                run_single(
                    asset=asset, timeframe=timeframe, df=df,
                    config=config,
                    output_dir=output_dir, config_yaml=config_yaml,
                    apply_results=apply_results,
                    status_writer=status_writer,
                    full_metrics=full_metrics,
                )

        except Exception as e:
            logger.error("Failed for %s %s: %s", asset, timeframe, e, exc_info=True)
            if status_writer:
                status_writer.fail(str(e))


if __name__ == "__main__":
    main()
