"""
Regime Hyperparameter Optimization Script.

Fetches OHLCV data from Binance Futures and runs Bayesian optimization
over 7 per-asset per-timeframe regime params with walk-forward CV.

Usage
-----
# Single asset
python app/regime/scripts/run_optimization.py \
    --asset BTCUSDT --timeframe 1h \
    --n-trials 100 --timeout 3600

# Multiple assets
python app/regime/scripts/run_optimization.py \
    --assets BTCUSDT ETHUSDT SUIUSDT \
    --timeframe 1h --n-trials 100

# Staged (3-stage hierarchical)
python app/regime/scripts/run_optimization.py \
    --asset BTCUSDT --timeframe 1h \
    --staged \
    --stage1-trials 50 --stage2-trials 50 --stage3-trials 100

# Universe mode (batch from YAML)
python app/regime/scripts/run_optimization.py \
    --universe universe.yaml --n-trials 100

# With monitoring (separate terminal)
python app/regime/scripts/monitor_optimization.py \
    --status-file app/regime/optimization/results/.optimization_status.json

Output
------
- Results JSON saved to app/regime/optimization/results/
- Best params written to app/regime/config/regime.yaml
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
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Ensure project root is on path
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import yaml

from app.regime.optimization import (
    OptimizationConfig,
    RegimeOptimizer,
    WalkForwardConfig,
)
from app.regime.optimization.models import OptimizationResult, OptimizationWeights

logger = logging.getLogger("app.regime.optimization")


# ---------------------------------------------------------------------------
# Status file writer (contract with monitor_optimization.py)
# ---------------------------------------------------------------------------

class StatusFileWriter:
    """Writes atomic JSON status file for the optimization monitor to read."""

    def __init__(self, output_dir: Path, asset: str, timeframe: str):
        self.status_path = output_dir / ".optimization_status.json"
        self._base = {
            "pid": os.getpid(),
            "asset": asset,
            "timeframe": timeframe,
            "start_time": datetime.now().isoformat(),
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        # Remove stale status file from previous runs before writing fresh state
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

    def complete(self, result: OptimizationResult) -> None:
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
        # Atomic write: tmp file + os.replace
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
    # Check cache first
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

    all_chunks = []
    while current_start < end_ts:
        try:
            chunk = connector.get_futures_klines(
                symbol=asset,
                interval=timeframe,
                start_time=current_start,
                end_time=end_ts,
                limit=1000,
            )
            if chunk.empty:
                break

            all_chunks.append(chunk)
            last_close_ts = int(chunk["close_time"].iloc[-1].timestamp() * 1000)
            next_start = last_close_ts + 1
            if next_start <= current_start:
                break
            current_start = next_start
            time.sleep(0.1)  # rate limit

        except Exception as e:
            logger.error("Error fetching chunk: %s", e)
            break

    if not all_chunks:
        raise ValueError(f"No data fetched for {asset}")

    df = pd.concat(all_chunks)
    df = df[~df.index.duplicated(keep="first")]
    df = df[(df.index >= start_dt) & (df.index <= end_dt)]
    df.sort_index(inplace=True)

    # Save to cache
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{asset}_{timeframe}_{start_date}_{end_date}.csv"
        df.to_csv(cache_path)
        logger.info("Cached %d bars to %s", len(df), cache_path)

    logger.info("Fetched %d bars for %s %s", len(df), asset, timeframe)
    return df


def load_data_from_csv(path: str) -> pd.DataFrame:
    """Load OHLCV data from a CSV file (fallback for offline use)."""
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
    """Backup regime.yaml before overwriting with new params."""
    p = Path(yaml_path)
    if p.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = p.with_name(f"{p.name}.bak.{ts}")
        shutil.copy2(p, backup)
        logger.info("Backed up %s -> %s", p.name, backup.name)


def _make_status_callback(status_writer: Optional[StatusFileWriter],
                          n_total: int, stage: str, stage_name: str):
    """Create an Optuna callback that updates the status file per trial."""
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


def _plateau_analysis(result: OptimizationResult, label: str) -> bool:
    """Check if optimization converged to a stable plateau. Returns True if converged."""
    trials = result.all_trials
    if len(trials) < 10:
        return False

    scores = [t.objective_value for t in trials]
    n = len(scores)
    best_so_far = np.maximum.accumulate(scores)

    tail_start = max(0, int(n * 0.8))
    tail_improvement = best_so_far[-1] - best_so_far[tail_start]
    total_improvement = best_so_far[-1] - best_so_far[0]

    top_n = max(3, n // 10)
    top_scores = sorted(scores, reverse=True)[:top_n]
    cv = np.std(top_scores) / (np.mean(top_scores) + 1e-10)

    plateau = tail_improvement < 0.005 and cv < 0.10

    logger.info("[%s] Plateau: tail_improvement=%.4f, top-10%% CV=%.4f -> %s",
                label, tail_improvement, cv,
                "CONVERGED" if plateau else "NOT YET")
    return plateau


def _print_comparison(yaml_path: str, new_params: Dict[str, Any],
                      asset: str, timeframe: str) -> None:
    """Print old vs new params side-by-side."""
    try:
        with open(yaml_path) as f:
            raw = yaml.safe_load(f) or {}
        old_params = raw.get("assets", {}).get(asset, {}).get(timeframe, {})
    except Exception:
        old_params = {}

    if not old_params:
        logger.info("No existing params for %s %s — fresh write", asset, timeframe)
        return

    print(f"\n  {'Param':<30} {'Old':>12}  {'New':>12}  {'Delta':>10}")
    print(f"  {'-'*68}")
    for k, new_v in sorted(new_params.items()):
        old_v = old_params.get(k)
        if old_v is not None and isinstance(old_v, (int, float)):
            delta = f"{new_v - old_v:+.4f}"
        else:
            delta = "new"
        old_str = f"{old_v:.4f}" if isinstance(old_v, float) else str(old_v or "—")
        new_str = f"{new_v:.4f}" if isinstance(new_v, float) else str(new_v)
        print(f"  {k:<30} {old_str:>12}  {new_str:>12}  {delta:>10}")


def _print_full_metrics(result: OptimizationResult, df: pd.DataFrame,
                        asset: str, timeframe: str) -> None:
    """Print comprehensive 5-tier metrics + regime distribution."""
    b = result.best_benchmarks
    divider = "=" * 70
    thin = "-" * 55

    print(f"\n{divider}")
    print(f"  {asset} {timeframe} -- Full Metrics")
    print(f"{divider}")
    print(f"  Objective:                  {result.best_objective:+.4f}")
    print(f"  Trials passed gate:         {result.n_trials_passed_gate}/{result.n_trials_total}")
    print(f"  Time:                       {result.total_time_seconds:.1f}s")

    print(f"\n  Tier 1 -- Strategy Utility (50%)")
    print(f"  {thin}")
    print(f"    Sharpe improvement:       {b.sharpe_improvement:+.4f}")
    print(f"    Drawdown reduction:       {b.drawdown_reduction:+.4f}")

    print(f"\n  Tier 2 -- Predictive Power (40%)")
    print(f"  {thin}")
    print(f"    Forward return IC:        {b.forward_return_ic:+.4f}")
    print(f"    Vol forecast error:       {b.vol_forecast_error:.4f}  (lower=better)")
    print(f"    IC decay score:           {b.ic_decay_score:+.4f}")

    print(f"\n  Tier 3 -- Statistical Validity (GATE)")
    print(f"  {thin}")
    print(f"    Levene p-value:           {b.levene_p_value:.6f}  (< 0.05 = PASS)")
    print(f"    Cohen's d:                {b.cohens_d:.4f}")
    print(f"    Gate status:              {'PASS' if b.passed_validity_gate else 'FAIL'}")

    print(f"\n  Tier 4 -- Stability (CONSTRAINT)")
    print(f"  {thin}")
    print(f"    Avg regime duration:      {b.avg_regime_duration:.1f} bars")
    print(f"    Flip-flop rate:           {b.flip_flop_rate:.4f}")
    print(f"    Transition entropy:       {b.transition_entropy:.4f}")

    print(f"\n  Tier 5 -- Changepoint Quality (10%)")
    print(f"  {thin}")
    print(f"    CP precision:             {b.cp_precision:.4f}")
    print(f"    CP recall:                {b.cp_recall:.4f}")
    print(f"    Detection lag:            {b.detection_lag:.1f} bars")

    # Regime distribution on full dataset
    try:
        from app.regime import RegimeOrchestrator
        orch = RegimeOrchestrator.create(asset, timeframe, **{
            k: int(v) if isinstance(v, float) and v == int(v) else v
            for k, v in result.best_params.items()
        })
        df_out = orch.analyze_series(df)
        counts = df_out["regime"].value_counts()
        total = len(df_out)

        print(f"\n  Regime Distribution")
        print(f"  {thin}")
        print(f"  {'Regime':<20} {'Count':>8}  {'%':>6}")
        print(f"  {'-'*38}")
        for regime, cnt in counts.items():
            print(f"  {regime:<20} {cnt:>8}  {cnt/total*100:>5.1f}%")

        df_out["ret"] = np.log(df["close"] / df["close"].shift(1))
        print(f"\n  {'Regime':<20} {'Mean ret':>10}  {'Std ret':>10}  {'Sharpe':>8}")
        print(f"  {'-'*54}")
        for regime in [
            "CLEAN_TREND_BULL", "CLEAN_TREND_BEAR", "CLEAN_TREND_FLAT",
            "VOLATILE_TREND_BULL", "VOLATILE_TREND_BEAR", "VOLATILE_TREND_FLAT",
            "QUIET_MR_RANGE", "QUIET_MR_SQUEEZE", "CHOPPY",
        ]:
            mask = df_out["regime"] == regime
            rets = df_out.loc[mask, "ret"].dropna()
            if len(rets) < 5:
                continue
            mu = rets.mean()
            sig = rets.std() + 1e-10
            sharpe = mu / sig * np.sqrt(8760)
            print(f"  {regime:<20} {mu:>10.6f}  {sig:>10.6f}  {sharpe:>8.3f}")
    except Exception as e:
        logger.warning("Regime distribution analysis failed: %s", e)

    print(f"\n{divider}\n")


def _print_summary(result: OptimizationResult) -> None:
    b = result.best_benchmarks
    print(f"\n{'='*60}")
    print(f"  {result.asset} {result.timeframe} -- Optimization Complete")
    print(f"{'='*60}")
    print(f"  Best objective:       {result.best_objective:.4f}")
    print(f"  Trials passed gate:   {result.n_trials_passed_gate}/{result.n_trials_total}")
    print(f"  Time:                 {result.total_time_seconds:.1f}s")
    print(f"  Best params:")
    for k, v in result.best_params.items():
        print(f"    {k:30s} = {v}")
    print(f"  Key metrics:")
    print(f"    Sharpe improvement:  {b.sharpe_improvement:+.3f}")
    print(f"    Drawdown reduction:  {b.drawdown_reduction:+.3f}")
    print(f"    Forward IC:          {b.forward_return_ic:+.3f}")
    print(f"    Levene p-value:      {b.levene_p_value:.4f}  "
          f"({'PASS' if b.passed_validity_gate else 'FAIL'})")
    print(f"    Avg regime duration: {b.avg_regime_duration:.1f} bars")
    print(f"    Flip-flop rate:      {b.flip_flop_rate:.3f}")
    print(f"    CP precision:        {b.cp_precision:.3f}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Optimization runners
# ---------------------------------------------------------------------------

def run_single(
    asset: str,
    timeframe: str,
    df: pd.DataFrame,
    config: OptimizationConfig,
    output_dir: Path,
    config_yaml: str,
    apply_results: bool = True,
    status_writer: Optional[StatusFileWriter] = None,
    full_metrics: bool = True,
) -> OptimizationResult:
    """Run single optimization and save results."""
    logger.info("=== Optimizing %s %s ===", asset, timeframe)

    cb = _make_status_callback(status_writer, config.n_trials, "single", "Full optimization")
    optimizer = RegimeOptimizer(config)
    result = optimizer.optimize(
        df, asset=asset, timeframe=timeframe,
        callbacks=[cb] if cb else None,
    )

    # Save JSON
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_path = output_dir / f"{asset}_{timeframe}_{ts}.json"
    result.save(str(out_path))
    logger.info("Saved result to %s", out_path)

    # Comparison + backup + apply
    if apply_results and Path(config_yaml).exists():
        _print_comparison(config_yaml, result.best_params, asset, timeframe)
        _backup_yaml(config_yaml)
        result.apply_to_config(config_yaml)
        logger.info("Applied params to %s", config_yaml)

    _print_summary(result)
    _plateau_analysis(result, f"{asset} {timeframe}")

    if full_metrics:
        _print_full_metrics(result, df, asset, timeframe)

    if status_writer:
        status_writer.complete(result)

    return result


def _pin_int(bounds):
    """Pin an int param at midpoint for staged fixing. Returns a (mid, mid+1) range."""
    lo, hi = bounds
    mid = (lo + hi) // 2
    return (mid, mid + 1)


def _pin_float(bounds):
    """Pin a float param at midpoint for staged fixing. Returns a (mid, mid+ε) range."""
    lo, hi = bounds
    mid = (lo + hi) / 2
    return (mid, mid + 1e-6)


def _narrow(val, full_range, factor=0.2):
    lo, hi = full_range
    margin = (hi - lo) * factor
    return (max(lo, val - margin), min(hi, val + margin))


def _narrow_int(val, full_range, factor=0.2):
    lo, hi = full_range
    margin = int((hi - lo) * factor)
    return (max(lo, val - margin), min(hi, val + margin))


def run_staged(
    asset: str,
    timeframe: str,
    df: pd.DataFrame,
    stage1_trials: int,
    stage2_trials: int,
    stage3_trials: int,
    base_config: OptimizationConfig,
    output_dir: Path,
    config_yaml: str,
    apply_results: bool = True,
    status_writer: Optional[StatusFileWriter] = None,
    plateau_stop: bool = False,
    full_metrics: bool = True,
) -> OptimizationResult:
    """
    3-stage hierarchical optimization to avoid overfitting.

    All stage configs are derived from base_config via dataclasses.replace so they
    always inherit the correct search space (scalping / swing / default).

    Stage 1: BCPD params only — all non-BCPD params pinned at midpoint of base_config range
    Stage 2: Vol + HMM + Aggregator + Hilbert — BCPD fixed at Stage 1 best
    Stage 3: Full 18-param polish — all params narrowed ±20% around Stage 2 best
    """
    logger.info("=== Staged optimization: %s %s ===", asset, timeframe)

    # ------------------------------------------------------------------
    # Stage 1: BCPD params only
    # All non-BCPD params are pinned at the midpoint of their base_config range
    # so Stage 1 cannot exploit them. Uses dataclasses.replace to ensure all
    # bounds come from base_config (not OptimizationConfig defaults).
    # ------------------------------------------------------------------
    logger.info("--- Stage 1: BCPD params (%d trials) ---", stage1_trials)
    s1_config = dataclasses.replace(
        base_config,
        n_trials=stage1_trials,
        timeout_seconds=base_config.timeout_seconds // 3,
        vol_high_percentile=_pin_float(base_config.vol_high_percentile),
        vol_lookback=_pin_int(base_config.vol_lookback),
        vol_hysteresis_band=_pin_float(base_config.vol_hysteresis_band),
        hmm_retrain_window=_pin_int(base_config.hmm_retrain_window),
        hmm_student_df=_pin_float(base_config.hmm_student_df),
        hmm_crisis_vol_mult=_pin_float(base_config.hmm_crisis_vol_mult),
        hurst_lookback=_pin_int(base_config.hurst_lookback),
        min_dwell_bars=_pin_int(base_config.min_dwell_bars),
        agg_direction_period=_pin_int(base_config.agg_direction_period),
        agg_bull_roc_thresh=_pin_float(base_config.agg_bull_roc_thresh),
        agg_vol_squeeze_pct=_pin_float(base_config.agg_vol_squeeze_pct),
        cp_position_decay=_pin_float(base_config.cp_position_decay),
        roc_std_window=_pin_int(base_config.roc_std_window),
        hilbert_min_period=_pin_int(base_config.hilbert_min_period),
        hilbert_max_period=_pin_int(base_config.hilbert_max_period),
    )
    cb1 = _make_status_callback(status_writer, stage1_trials, "stage1", "BCPD params")
    r1 = RegimeOptimizer(s1_config).optimize(
        df, asset=asset, timeframe=timeframe,
        n_trials=stage1_trials, callbacks=[cb1] if cb1 else None,
    )
    _print_summary(r1)
    s1_converged = _plateau_analysis(r1, "Stage 1 (BCPD)")

    fixed_lambda = r1.best_params["bcpd_hazard_lambda"]
    fixed_threshold = r1.best_params["bcpd_signal_threshold"]
    fixed_shape = r1.best_params.get("bcpd_hazard_shape",
                                      (base_config.bcpd_hazard_shape[0] + base_config.bcpd_hazard_shape[1]) / 2)
    logger.info("Stage 1 best: hazard_lambda=%.1f, threshold=%.3f, shape=%.3f",
                fixed_lambda, fixed_threshold, fixed_shape)

    # ------------------------------------------------------------------
    # Stage 2: All non-BCPD params free within base_config bounds
    # BCPD pinned at Stage 1 best. Uses dataclasses.replace so bounds
    # stay within scalping / swing / default range.
    # ------------------------------------------------------------------
    if plateau_stop and s1_converged:
        stage2_trials = max(10, stage2_trials // 2)
        logger.info("Plateau detected -- reducing Stage 2 to %d trials", stage2_trials)

    logger.info("--- Stage 2: Vol + HMM + Aggregator params (%d trials) ---", stage2_trials)
    s2_config = dataclasses.replace(
        base_config,
        n_trials=stage2_trials,
        timeout_seconds=base_config.timeout_seconds // 3,
        hazard_lambda=(fixed_lambda, fixed_lambda + 0.01),
        signal_threshold=(fixed_threshold, fixed_threshold + 0.001),
        bcpd_hazard_shape=(fixed_shape, fixed_shape + 0.001),
    )
    cb2 = _make_status_callback(status_writer, stage2_trials, "stage2", "Vol + HMM + Aggregator")
    r2 = RegimeOptimizer(s2_config).optimize(
        df, asset=asset, timeframe=timeframe,
        n_trials=stage2_trials, callbacks=[cb2] if cb2 else None,
    )
    _print_summary(r2)
    s2_converged = _plateau_analysis(r2, "Stage 2 (Vol+HMM+Agg)")

    logger.info("Stage 2 best: vol_pct=%.1f, vol_lookback=%d, hmm_window=%d, hurst=%d",
                r2.best_params["vol_high_percentile"],
                r2.best_params["vol_lookback"],
                r2.best_params["hmm_retrain_window"],
                r2.best_params["hurst_lookback"])

    # ------------------------------------------------------------------
    # Stage 3: Full 18-param polish
    # All params narrowed ±20% around Stage 2 best, clipped to base_config bounds.
    # Uses dataclasses.replace — no param can escape the preset range.
    # ------------------------------------------------------------------
    if plateau_stop and s2_converged:
        stage3_trials = max(10, stage3_trials // 2)
        logger.info("Plateau detected -- reducing Stage 3 to %d trials", stage3_trials)

    logger.info("--- Stage 3: Full 18-param polish (%d trials) ---", stage3_trials)
    bp = r2.best_params
    s3_config = dataclasses.replace(
        base_config,
        n_trials=stage3_trials,
        timeout_seconds=base_config.timeout_seconds // 3,
        hazard_lambda=_narrow(fixed_lambda, base_config.hazard_lambda),
        signal_threshold=_narrow(fixed_threshold, base_config.signal_threshold),
        bcpd_hazard_shape=_narrow(fixed_shape, base_config.bcpd_hazard_shape),
        vol_high_percentile=_narrow(bp["vol_high_percentile"], base_config.vol_high_percentile),
        vol_lookback=_narrow_int(bp["vol_lookback"], base_config.vol_lookback),
        vol_hysteresis_band=_narrow(bp["vol_hysteresis_band"], base_config.vol_hysteresis_band),
        hmm_retrain_window=_narrow_int(bp["hmm_retrain_window"], base_config.hmm_retrain_window),
        hmm_student_df=_narrow(bp["hmm_student_df"], base_config.hmm_student_df),
        hmm_crisis_vol_mult=_narrow(bp["hmm_crisis_vol_mult"], base_config.hmm_crisis_vol_mult),
        hurst_lookback=_narrow_int(bp["hurst_lookback"], base_config.hurst_lookback),
        min_dwell_bars=_narrow_int(bp["min_dwell_bars"], base_config.min_dwell_bars),
        agg_direction_period=_narrow_int(bp["agg_direction_period"], base_config.agg_direction_period),
        agg_bull_roc_thresh=_narrow(bp["agg_bull_roc_thresh"], base_config.agg_bull_roc_thresh),
        agg_vol_squeeze_pct=_narrow(bp["agg_vol_squeeze_pct"], base_config.agg_vol_squeeze_pct),
        cp_position_decay=_narrow(bp["agg_cp_position_decay"], base_config.cp_position_decay),
        roc_std_window=_narrow_int(bp["roc_std_window"], base_config.roc_std_window),
        hilbert_min_period=_narrow_int(bp["hilbert_min_period"], base_config.hilbert_min_period),
        hilbert_max_period=_narrow_int(bp["hilbert_max_period"], base_config.hilbert_max_period),
    )
    cb3 = _make_status_callback(status_writer, stage3_trials, "stage3", "Full polish")
    final = RegimeOptimizer(s3_config).optimize(
        df, asset=asset, timeframe=timeframe,
        n_trials=stage3_trials, callbacks=[cb3] if cb3 else None,
    )

    # Save and apply
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_path = output_dir / f"{asset}_{timeframe}_{ts}_staged.json"
    final.save(str(out_path))
    logger.info("Saved staged result to %s", out_path)

    if apply_results and Path(config_yaml).exists():
        _print_comparison(config_yaml, final.best_params, asset, timeframe)
        _backup_yaml(config_yaml)
        final.apply_to_config(config_yaml)
        logger.info("Applied params to %s", config_yaml)

    _print_summary(final)
    _plateau_analysis(final, "Stage 3 (Final)")

    if full_metrics:
        _print_full_metrics(final, df, asset, timeframe)

    if status_writer:
        status_writer.complete(final)

    return final


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_config(args) -> OptimizationConfig:
    wf_config = WalkForwardConfig(
        train_bars=args.train_bars,
        test_bars=args.test_bars,
        step_bars=args.step_bars,
        purge_bars=args.purge_bars,
        min_train_bars=args.min_train_bars,
    )
    run_kwargs = dict(
        n_trials=args.n_trials,
        timeout_seconds=args.timeout,
        n_jobs=args.n_jobs,
        sampler=args.sampler,
        pruner=args.pruner,
        soft_gate=not args.hard_gate,
        walk_forward=wf_config,
    )
    # --objective-mode overrides the trading style default only when explicitly set
    objective_mode = getattr(args, "objective_mode", None)

    style = getattr(args, "trading_style", "default")
    if style == "scalping":
        config = OptimizationConfig.scalping(**run_kwargs)
    elif style == "swing":
        config = OptimizationConfig.swing(**run_kwargs)
    else:
        config = OptimizationConfig(objective_mode=objective_mode or "full", **run_kwargs)

    # Explicit --objective-mode always wins over preset default
    if objective_mode:
        config.objective_mode = objective_mode

    return config


def _load_universe(path: str) -> List[Dict[str, Any]]:
    """Load asset universe from YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    entries = data.get("assets", [])
    if not entries:
        raise ValueError(f"Universe file {path} has no assets defined")
    return entries


def main():
    parser = argparse.ArgumentParser(
        description="Regime hyperparameter optimization via Binance data",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Asset / timeframe
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--asset", type=str, help="Single asset (e.g. BTCUSDT)")
    group.add_argument("--assets", nargs="+", help="Multiple assets")
    group.add_argument("--universe", type=str,
                       help="YAML file with asset/timeframe universe")

    parser.add_argument("--timeframe", type=str, default="1h",
                        help="Timeframe (e.g. 1h, 4h, 1d)")

    # Data source
    parser.add_argument("--start-date", type=str, default="2023-01-01",
                        help="Start date for historical data (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default="2026-03-01",
                        help="End date for historical data (YYYY-MM-DD)")
    parser.add_argument("--csv", type=str, default=None,
                        help="Load data from CSV instead of Binance")
    parser.add_argument("--cache-dir", type=str,
                        default="app/regime/optimization/results",
                        help="Directory for data caching")

    # Optimization settings
    parser.add_argument("--n-trials", type=int, default=100)
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Timeout in seconds")
    parser.add_argument("--n-jobs", type=int, default=1,
                        help="Parallel Optuna jobs")
    parser.add_argument("--sampler", type=str, default="tpe",
                        choices=["tpe", "random", "cmaes"])
    parser.add_argument("--pruner", type=str, default="median",
                        choices=["median", "hyperband", "none"])
    parser.add_argument("--hard-gate", action="store_true",
                        help="Fail trials that don't pass statistical validity gate")
    parser.add_argument("--objective-mode", type=str, default=None,
                        choices=["full", "classification", "balanced"],
                        help="Override objective weights. Default: classification for scalping, "
                             "balanced for swing, full otherwise.")
    parser.add_argument("--trading-style", type=str, default="default",
                        choices=["default", "scalping", "swing"],
                        help="Preset search space bounds tuned for the strategy horizon. "
                             "scalping: 1–8 bar holds, fast HMM/BCPD/Hurst. "
                             "swing: 12–80 bar holds, slow HMM/BCPD/Hurst.")

    # Walk-forward settings
    parser.add_argument("--train-bars", type=int, default=4320,
                        help="Training window size in bars")
    parser.add_argument("--test-bars", type=int, default=720,
                        help="Test window size in bars")
    parser.add_argument("--step-bars", type=int, default=720,
                        help="Walk-forward step size in bars")
    parser.add_argument("--purge-bars", type=int, default=24,
                        help="Gap between train and test to prevent leakage")
    parser.add_argument("--min-train-bars", type=int, default=2160,
                        help="Minimum training bars before a fold is valid")

    # Staged optimization
    parser.add_argument("--staged", action="store_true",
                        help="Run 3-stage hierarchical optimization")
    parser.add_argument("--stage1-trials", type=int, default=50)
    parser.add_argument("--stage2-trials", type=int, default=50)
    parser.add_argument("--stage3-trials", type=int, default=100)
    parser.add_argument("--plateau-stop", action="store_true",
                        help="Auto-reduce trial budget on convergence")

    # Output
    parser.add_argument("--output-dir", type=str,
                        default="app/regime/optimization/results",
                        help="Directory to save result JSONs")
    parser.add_argument("--config-yaml", type=str,
                        default="app/regime/config/regime.yaml",
                        help="Target YAML to write best params")
    parser.add_argument("--no-apply", action="store_true",
                        help="Skip writing to regime.yaml")
    parser.add_argument("--no-status", action="store_true",
                        help="Skip writing status file for monitor")
    parser.add_argument("--no-full-metrics", action="store_true",
                        help="Skip full metrics output after optimization")

    # Logging
    parser.add_argument("--log-level", type=str, default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    # n_jobs safety on macOS
    if args.n_jobs > 1 and platform.system() == "Darwin":
        logger.warning(
            "n_jobs=%d on macOS may deadlock due to BLAS thread oversubscription. "
            "Consider --n-jobs 1 for reliability.", args.n_jobs
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

    for entry in universe:
        asset = entry["symbol"]
        timeframe = entry.get("timeframe", args.timeframe)
        start_date = entry.get("start_date", args.start_date)
        end_date = entry.get("end_date", args.end_date)

        # Status file
        status_writer = None
        if not args.no_status:
            status_writer = StatusFileWriter(output_dir, asset, timeframe)

        try:
            # Load data
            if args.csv:
                df = load_data_from_csv(args.csv)
            else:
                df = fetch_data(asset, timeframe, start_date, end_date,
                                cache_dir=cache_dir)

            min_bars = config.walk_forward.train_bars + config.walk_forward.test_bars
            if len(df) < min_bars:
                logger.warning(
                    "Not enough data for %s %s: got %d bars, need %d",
                    asset, timeframe, len(df), min_bars,
                )
                continue

            if args.staged:
                run_staged(
                    asset=asset,
                    timeframe=timeframe,
                    df=df,
                    stage1_trials=args.stage1_trials,
                    stage2_trials=args.stage2_trials,
                    stage3_trials=args.stage3_trials,
                    base_config=config,
                    output_dir=output_dir,
                    config_yaml=config_yaml,
                    apply_results=apply_results,
                    status_writer=status_writer,
                    plateau_stop=args.plateau_stop,
                    full_metrics=full_metrics,
                )
            else:
                run_single(
                    asset=asset,
                    timeframe=timeframe,
                    df=df,
                    config=config,
                    output_dir=output_dir,
                    config_yaml=config_yaml,
                    apply_results=apply_results,
                    status_writer=status_writer,
                    full_metrics=full_metrics,
                )

        except Exception as exc:
            logger.error("Optimization failed for %s %s: %s", asset, timeframe, exc)
            if status_writer:
                status_writer.fail(str(exc))


if __name__ == "__main__":
    main()
