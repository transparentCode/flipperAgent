#!/usr/bin/env python3
"""
Regression Hyperparameter Optimization CLI (V2 — MOTPE).

Runs Multi-Objective TPE optimization on the regression pipeline with
3-way walk-forward CV and 5-tier benchmark scoring.

Usage:
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
      python app/regression/scripts/run_optimization.py \
        --asset ETHUSDT --timeframe 1h \
        --start-date 2022-01-01 --end-date 2026-03-01 \
        --n-trials 50 --timeout 600

    python app/regression/scripts/run_optimization.py --asset BTCUSDT --timeframe 4h --lookback 180
    python app/regression/scripts/run_optimization.py --help
"""

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd

from app.connectors.BinanceConnector import BinanceConnector
from libs.regression.config.resolver import ConfigResolver
from libs.regression.config.schema import OrchestratorConfig
from libs.regression.optimization.models import (
    RegressionOptimizationConfig,
    RegressionOptimizationResult,
)
from libs.regression.optimization.optimizer import RegressionMOTPEOptimizer
from libs.regression.optimization.pipeline_factory import build_pipeline_factory
from libs.regression.pipeline import RegressionPipeline

logger = logging.getLogger("app.regression.scripts.run_optimization")

_RESULTS_DIR = Path(__file__).parent.parent / "optimization" / "results"
_DEFAULT_YAML = Path(__file__).parent.parent / "config" / "regression.yaml"
_OPT_V2_YAML = Path(__file__).parent.parent / "optimization" / "config" / "optimization.yaml"

_FETCH_RATE_LIMIT_S = 0.3


def parse_args(argv=None):
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Optimize regression pipeline hyperparameters (V2 MOTPE)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Date-range run with single-threaded BLAS (recommended)
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \\
      python app/regression/scripts/run_optimization.py \\
        --asset ETHUSDT --timeframe 1h \\
        --start-date 2022-01-01 --end-date 2026-03-01 \\
        --n-trials 50 --timeout 600

    # Lookback-based (90 days from today)
    python app/regression/scripts/run_optimization.py --asset BTCUSDT --timeframe 1h

    # With V2 YAML config
    python app/regression/scripts/run_optimization.py --opt-config app/regression/optimization/config/optimization.yaml

    # Quick test
    python app/regression/scripts/run_optimization.py --n-trials 5 --timeout 60 --quiet --no-trial-history
        """,
    )

    parser.add_argument(
        "-a", "--asset",
        type=str,
        default="BTCUSDT",
        help="Trading pair (default: BTCUSDT)",
    )
    parser.add_argument(
        "-t", "--timeframe",
        type=str,
        default="1h",
        help="Timeframe (default: 1h)",
    )
    parser.add_argument(
        "--n-trials",
        type=int,
        default=None,
        help="Number of Optuna trials (overrides YAML; default from config: 200)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Timeout in seconds (overrides YAML; default from config: 3600)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to regression pipeline YAML config (optional; uses defaults)",
    )
    parser.add_argument(
        "--opt-config",
        type=str,
        default=None,
        help="Path to optimization YAML config (optional; uses defaults)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date for data range (YYYY-MM-DD). Overrides --lookback.",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date for data range (YYYY-MM-DD). Defaults to today if --start-date set.",
    )
    parser.add_argument(
        "-l", "--lookback",
        type=int,
        default=90,
        help="Lookback days from today (default: 90). Ignored if --start-date set.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for MOTPE sampler (overrides YAML; default: 42)",
    )
    parser.add_argument(
        "--expanding-window",
        action="store_true",
        default=None,
        help="Use expanding train window (default: fixed-size)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Explicit output path (must be under optimization/results/)",
    )
    parser.add_argument(
        "--no-trial-history",
        action="store_true",
        help="Omit per-trial history from saved JSON (smaller file)",
    )
    parser.add_argument(
        "--log-interval",
        type=int,
        default=10,
        help="Print progress every N trials (default: 10)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )
    parser.add_argument(
        "--step-bars",
        type=int,
        default=None,
        help="Walk-forward step size in bars (overrides YAML; default: 720).",
    )
    parser.add_argument(
        "--train-bars",
        type=int,
        default=None,
        help="Walk-forward training window in bars (overrides YAML; default: 4320).",
    )

    return parser.parse_args(argv)


def _parse_date(date_str: str) -> datetime:
    """Parse YYYY-MM-DD string to datetime."""
    return datetime.strptime(date_str, "%Y-%m-%d")


def _fetch_paginated(
    connector: BinanceConnector,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    quiet: bool = False,
) -> pd.DataFrame:
    """Fetch klines with pagination (Binance returns max 1000 per call)."""
    all_data: list[pd.DataFrame] = []
    current_start = start_ms

    while current_start < end_ms:
        df = connector.get_futures_klines(symbol, interval, current_start, end_ms)
        if df.empty:
            break
        all_data.append(df)
        last_ms = int(df.index[-1].timestamp() * 1000)
        if last_ms >= end_ms or (last_ms == current_start and len(df) == 1):
            break
        current_start = last_ms + 1
        time.sleep(_FETCH_RATE_LIMIT_S)

    if not all_data:
        return pd.DataFrame()
    full = pd.concat(all_data)
    full = full[~full.index.duplicated(keep="last")]
    full.sort_index(inplace=True)
    return full


def fetch_data(
    asset: str,
    timeframe: str,
    lookback_days: int = 90,
    start_date: str | None = None,
    end_date: str | None = None,
    quiet: bool = False,
) -> pd.DataFrame:
    """Fetch OHLCV data via BinanceConnector with pagination.

    If start_date is provided, fetches [start_date, end_date] with auto-pagination
    (Binance API returns max 1000 bars per call).
    Otherwise falls back to lookback_days from today.
    """
    connector = BinanceConnector()
    if start_date is not None:
        start_dt = _parse_date(start_date)
        end_dt = _parse_date(end_date) if end_date else datetime.now()
        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)
        if not quiet:
            print(f"Fetching {asset} {timeframe} ({start_date} to {end_date or 'now'})...")
    else:
        if not quiet:
            print(f"Fetching {asset} {timeframe} ({lookback_days} days)...")
        start_ms = int((datetime.now().timestamp() - lookback_days * 86400) * 1000)
        end_ms = int(datetime.now().timestamp() * 1000)
    df = _fetch_paginated(connector, asset, timeframe, start_ms, end_ms, quiet)
    if not quiet:
        print(f"  {len(df)} bars loaded")
    return df


def build_config(args) -> RegressionOptimizationConfig:
    """Build V2 RegressionOptimizationConfig from YAML + CLI overrides."""
    # Start from YAML if provided, else defaults
    if args.opt_config is not None:
        config = RegressionOptimizationConfig.from_yaml(args.opt_config)
    elif _OPT_V2_YAML.exists():
        config = RegressionOptimizationConfig.from_yaml(str(_OPT_V2_YAML))
    else:
        config = RegressionOptimizationConfig()

    # Apply CLI overrides (only if explicitly set)
    overrides = {}
    if args.n_trials is not None:
        overrides["n_trials"] = args.n_trials
    if args.timeout is not None:
        overrides["timeout_seconds"] = args.timeout
    if args.seed is not None:
        overrides["seed"] = args.seed
    if args.expanding_window is not None:
        overrides["expanding_window"] = args.expanding_window
    if args.step_bars is not None:
        overrides["step_bars"] = args.step_bars
    if args.train_bars is not None:
        overrides["train_bars"] = args.train_bars

    if overrides:
        config = config.model_copy(update=overrides)
    return config


def build_resolver(config_path: str | None):
    """Build ConfigResolver from YAML.

    Falls back to the default regression.yaml shipped with the module.
    """
    if config_path is not None:
        return ConfigResolver.from_yaml(config_path)
    # Auto-resolve default config
    default = str(_DEFAULT_YAML)
    if not _DEFAULT_YAML.exists():
        raise FileNotFoundError(
            f"Default config not found at {default}. Use --config to specify."
        )
    return ConfigResolver.from_yaml(default)


# Pipeline factory is now imported from the shared module at top-level.
# (app.regression.optimization.pipeline_factory.build_pipeline_factory)


def make_progress_callback(log_interval: int, quiet: bool):
    """Create an Optuna callback that prints trial progress (multi-objective aware)."""
    if quiet:
        return None

    def _callback(study, trial):
        n = trial.number + 1
        pruned = len([t for t in study.trials if t.state.name == "PRUNED"])
        if n % log_interval == 0 or n == 1:
            n_pareto = len(study.best_trials)
            status = "pruned" if trial.state.name == "PRUNED" else f"pareto={n_pareto}"
            print(f"  Trial {n:>4d} | {status} | pruned so far: {pruned}")

    return _callback


# ---------------------------------------------------------------------------
# Status file writer (contract with monitor_optimization.py)
# ---------------------------------------------------------------------------

_STATUS_FILENAME = ".optimization_status.json"


class StatusFileWriter:
    """Writes atomic JSON status file for the monitor to read.

    The status file is written to ``_RESULTS_DIR / .optimization_status.json``
    and is overwritten on every trial completion.  The monitor polls this
    single well-known path — no filename guessing needed.
    """

    def __init__(self, output_dir: Path, asset: str, timeframe: str, n_trials: int):
        self.status_path = output_dir / _STATUS_FILENAME
        self._base = {
            "pid": os.getpid(),
            "asset": asset,
            "timeframe": timeframe,
            "n_trials_target": n_trials,
            "start_time": datetime.now().isoformat(),
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        # Remove stale status file from previous runs
        if self.status_path.exists():
            self.status_path.unlink()
        self._write(
            status="starting",
            trial_current=0,
            best_objective_values=[],
            best_params={},
            n_trials_passed_gate=0,
            n_trials_pruned=0,
        )

    def update(
        self,
        *,
        trial_current: int,
        best_objective_values: list,
        best_params: dict,
        n_passed_gate: int,
        n_pruned: int,
    ) -> None:
        self._write(
            status="running",
            trial_current=trial_current,
            best_objective_values=best_objective_values,
            best_params=best_params,
            n_trials_passed_gate=n_passed_gate,
            n_trials_pruned=n_pruned,
        )

    def complete(self, result: RegressionOptimizationResult) -> None:
        self._write(
            status="completed",
            trial_current=result.n_trials_total,
            best_objective_values=list(result.best_objective_values),
            best_params=result.best_params,
            n_trials_passed_gate=result.n_trials_passed_gate,
            n_trials_pruned=0,
        )

    def fail(self, error_msg: str) -> None:
        self._write(
            status="failed",
            trial_current=0,
            best_objective_values=[],
            best_params={},
            n_trials_passed_gate=0,
            n_trials_pruned=0,
            error=error_msg,
        )

    def _write(self, **fields) -> None:
        data = {**self._base, "last_update": datetime.now().isoformat(), **fields}
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=self.status_path.parent, suffix=".tmp",
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


def make_status_callback(status_writer: StatusFileWriter | None, n_trials: int):
    """Create an Optuna callback that updates the status file per trial."""
    if status_writer is None:
        return None

    def _callback(study, trial):
        # Multi-objective: pick first Pareto-front trial's values as "best"
        best_trials = study.best_trials
        if best_trials:
            best_values = list(best_trials[0].values)
            best_params = best_trials[0].params
        else:
            best_values = []
            best_params = {}
        n_passed = sum(
            1 for t in study.trials
            if t.state.name == "COMPLETE"
            and t.user_attrs.get("passed_gate", False)
        )
        n_pruned = sum(1 for t in study.trials if t.state.name == "PRUNED")
        status_writer.update(
            trial_current=trial.number + 1,
            best_objective_values=best_values,
            best_params=best_params,
            n_passed_gate=n_passed,
            n_pruned=n_pruned,
        )

    return _callback


def auto_output_path(asset: str, timeframe: str) -> str:
    """Generate timestamped output path under results/."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{asset}_{timeframe}_{ts}.json"
    return str(_RESULTS_DIR / filename)


def print_results(result: RegressionOptimizationResult, quiet: bool = False):
    """Print formatted optimization results to stdout."""
    if quiet:
        return

    b = result.best_benchmarks
    gate_rate = (
        result.n_trials_passed_gate / result.n_trials_total * 100
        if result.n_trials_total > 0 else 0.0
    )
    minutes = result.total_time_seconds / 60
    obj_vals = result.best_objective_values

    print()
    print("=" * 65)
    print("  REGRESSION OPTIMIZATION RESULTS (V2 MOTPE)")
    print("=" * 65)
    print(f"  Asset:     {result.asset}")
    print(f"  Timeframe: {result.timeframe}")
    print(f"  Timestamp: {result.timestamp.isoformat()}")
    print()
    print(f"  Best Objectives: dir={obj_vals[0]:.4f}  cov={obj_vals[1]:.4f}  sharpe={obj_vals[2]:.4f}")
    print(f"  Trials:         {result.n_trials_total}")
    print(f"  Gate Pass Rate: {result.n_trials_passed_gate}/{result.n_trials_total} ({gate_rate:.1f}%)")
    print(f"  Total Time:     {minutes:.1f} min ({result.total_time_seconds:.0f}s)")
    print()
    print("  BENCHMARK BREAKDOWN")
    print(f"    Tier 1 Direction Accuracy:   {b.weighted_direction_score:.4f}")
    print(f"    Tier 2 Band Coverage:        {b.band_coverage_pct * 100:.2f}%")
    print(f"    Tier 2 Band Width Stability: {b.band_width_stability:.4f}")
    print(f"    Tier 3 Durbin-Watson (GATE): {b.durbin_watson:.3f} {'PASS' if b.passed_residual_gate else 'FAIL'}")
    print(f"    Tier 4 Confidence Rho (CON): {b.confidence_return_spearman:.4f} {'PASS' if b.passed_confidence_constraint else 'FAIL'}")
    print(f"    Tier 5 Confidence Sharpe:    {b.confidence_sharpe:.4f}")
    print(f"    Tier 5 Sharpe Improvement:   {b.sharpe_improvement:.4f}")
    print()
    print("  BEST PARAMETERS")
    for key, value in sorted(result.best_params.items()):
        if isinstance(value, float):
            print(f"    {key}: {value:.6f}")
        else:
            print(f"    {key}: {value}")
    print("=" * 65)


def main(argv=None) -> int:
    """Entry point."""
    args = parse_args(argv)

    if not args.quiet:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )

    # 1. Fetch data
    try:
        df = fetch_data(
            args.asset, args.timeframe,
            lookback_days=args.lookback,
            start_date=args.start_date,
            end_date=args.end_date,
            quiet=args.quiet,
        )
    except Exception as exc:
        print(f"ERROR: Failed to fetch data: {exc}", file=sys.stderr)
        return 1

    if len(df) < 500:
        print(
            f"ERROR: Insufficient data — got {len(df)} bars, need at least 500",
            file=sys.stderr,
        )
        return 1

    # 2. Build config, resolver, and pipeline factory
    opt_config = build_config(args)
    resolver = build_resolver(args.config)
    pipeline_factory = build_pipeline_factory(resolver)

    # Resolve orchestrator config for search space building
    orch_config = OrchestratorConfig()
    try:
        from libs.regression.config.schema import OrchestratorConfig as OC
        resolved = resolver.resolve(args.asset, args.timeframe)
        if hasattr(resolved, "orchestrator"):
            orch_config = resolved.orchestrator
    except Exception:
        pass  # Fall back to default OrchestratorConfig

    # 3. Build optimizer
    optimizer = RegressionMOTPEOptimizer(
        config=opt_config,
        orch_config=orch_config,
        pipeline_factory=pipeline_factory,
    )

    # 4. Build status writer
    n_trials = opt_config.n_trials
    output_path = args.output or auto_output_path(args.asset, args.timeframe)
    status_writer = StatusFileWriter(
        _RESULTS_DIR, args.asset, args.timeframe, n_trials,
    )

    # 5. Run optimization
    if not args.quiet:
        print(f"\nStarting V2 MOTPE optimization: {args.asset} {args.timeframe}")
        print(f"  Trials: {n_trials} | Timeout: {opt_config.timeout_seconds}s | Seed: {opt_config.seed}")
        print(f"  Status file: {status_writer.status_path}\n")

    try:
        result = optimizer.optimize(
            df,
            asset=args.asset,
            timeframe=args.timeframe,
        )
    except ImportError as exc:
        print(f"ERROR: Missing dependency: {exc}", file=sys.stderr)
        print("  Install with: pip install optuna", file=sys.stderr)
        status_writer.fail(str(exc))
        return 1
    except Exception as exc:
        print(f"ERROR: Optimization failed: {exc}", file=sys.stderr)
        status_writer.fail(str(exc))
        return 1

    # 6. Print results
    print_results(result, args.quiet)
    status_writer.complete(result)

    # 7. Save results
    try:
        if args.no_trial_history:
            result.all_trials = []
        result.save(output_path)
        if not args.quiet:
            print(f"\nResults saved to: {output_path}")
    except Exception as exc:
        print(f"WARNING: Could not save results: {exc}", file=sys.stderr)

    # 8. Exit code
    gate_rate = (
        result.n_trials_passed_gate / result.n_trials_total
        if result.n_trials_total > 0 else 0.0
    )
    return 0 if gate_rate > 0.1 else 1


if __name__ == "__main__":
    sys.exit(main())
