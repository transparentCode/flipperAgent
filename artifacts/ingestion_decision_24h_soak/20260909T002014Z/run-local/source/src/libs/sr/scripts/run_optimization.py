#!/usr/bin/env python3
"""
S/R Two-Stage Optimization CLI.

Runs Bayesian optimization on the S/R pipeline with Stage 1 (universe-wide
global) followed by Stage 2 (per-asset kernel tuning) using walk-forward CV.

Usage:
    python app/sr/scripts/run_optimization.py \\
        --assets BTCUSDT,ETHUSDT --timeframes 1h \\
        --n-trials 50 --timeout 3600

    python app/sr/scripts/run_optimization.py \\
        --assets BTCUSDT --timeframes 1h,4h \\
        --start-date 2023-01-01 --end-date 2026-03-01 \\
        --apply --dry-run

    python app/sr/scripts/run_optimization.py --help
"""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

logger = logging.getLogger("app.sr.scripts.run_optimization")

from app.sr.optimization._shared import RESULTS_DIR as _RESULTS_DIR
_DEFAULT_YAML = Path(__file__).parent.parent / "config" / "sr.yaml"
_MIN_ACCEPT_RATE = 0.1  # Stage 2 acceptance threshold for exit code 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Two-stage S/R hyperparameter optimization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Single asset, 1h
    python app/sr/scripts/run_optimization.py -a BTCUSDT -t 1h --n-trials 50

    # Multi-asset with date range
    python app/sr/scripts/run_optimization.py \\
        -a BTCUSDT,ETHUSDT,SOLUSDT -t 1h,4h \\
        --start-date 2023-01-01 --end-date 2026-03-01 \\
        --n-trials 100 --timeout 7200

    # Apply best params to YAML (with diff preview)
    python app/sr/scripts/run_optimization.py -a BTCUSDT -t 1h \\
        --n-trials 50 --apply --dry-run

    # Quick test run
    python app/sr/scripts/run_optimization.py --n-trials 5 --timeout 60 --quiet
        """,
    )

    parser.add_argument(
        "-a", "--assets",
        type=str,
        default="BTCUSDT",
        help="Comma-separated trading pairs (default: BTCUSDT)",
    )
    parser.add_argument(
        "-t", "--timeframes",
        type=str,
        default="1h",
        help="Comma-separated timeframes (default: 1h)",
    )
    parser.add_argument(
        "--n-trials",
        type=int,
        default=50,
        help="Stage 1 Optuna trials (default: 50)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=3600,
        help="Stage 1 timeout in seconds (default: 3600)",
    )
    parser.add_argument(
        "--stage2-n-trials",
        type=int,
        default=30,
        help="Stage 2 per-asset Optuna trials (default: 30)",
    )
    parser.add_argument(
        "--stage2-timeout",
        type=int,
        default=600,
        help="Stage 2 per-asset timeout in seconds (default: 600)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to sr.yaml config (optional; uses defaults otherwise)",
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
        help="End date for data range (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "-l", "--lookback",
        type=int,
        default=90,
        help="Lookback days from today (default: 90). Ignored if --start-date set.",
    )
    parser.add_argument(
        "--sampler",
        type=str,
        choices=["tpe", "cma-es", "random"],
        default="tpe",
        help="Optuna sampler (default: tpe)",
    )
    parser.add_argument(
        "--fold-stride",
        type=int,
        default=3,
        help="Stage 2 fold stride: evaluate every Nth fold during trials "
             "(default: 3). Higher = faster but noisier. Final validation "
             "always uses all folds.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Explicit output path (must be under optimization/results/)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write best params back to YAML config. Default: off.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --apply, preview YAML diff without writing.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )
    parser.add_argument(
        "--log-interval",
        type=int,
        default=10,
        help="Print progress every N trials (default: 10)",
    )
    parser.add_argument(
        "--no-trial-history",
        action="store_true",
        help="Omit per-trial history from saved JSON",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for Optuna samplers (default: from YAML or 42)",
    )

    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Config builders
# ---------------------------------------------------------------------------

def build_configs(args: argparse.Namespace):
    """Build Stage 1 and Stage 2 optimizer configs from CLI args.

    Returns
    -------
    tuple
        (UniverseOptimizationConfig, AssetOptimizationConfig, UniverseSRConfig)
    """
    from app.sr.optimization.asset_optimizer import AssetOptimizationConfig
    from app.sr.optimization.universe_optimizer import UniverseOptimizationConfig
    from app.sr.universe.config import AssetSRConfig, UniverseSRConfig

    assets = [a.strip() for a in args.assets.split(",")]
    timeframes = [t.strip() for t in args.timeframes.split(",")]

    # Stage 1 config
    stage1_kwargs: dict = {
        "n_trials": args.n_trials,
        "timeout_s": float(args.timeout),
    }

    # If a YAML config is provided (or default exists), try to source optimizer defaults
    config_path = args.config if args.config is not None else str(_DEFAULT_YAML)
    raw = None
    try:
        from app.sr.config_resolver import SRConfigResolver
        from app.utils.ConfigLoader import ConfigLoader

        raw = ConfigLoader.load(config_path)
        resolver = SRConfigResolver()
        opt_config = resolver.resolve_typed_optimization_config(raw)
        stage1_config = UniverseOptimizationConfig.from_resolved_config(opt_config)
        # Override with CLI args (CLI takes precedence)
        stage1_config = UniverseOptimizationConfig(
            n_trials=args.n_trials,
            timeout_s=float(args.timeout),
            parameter_space=stage1_config.parameter_space,
        )
    except Exception as exc:
        logger.warning("Could not load optimizer config from YAML: %s", exc)
        stage1_config = UniverseOptimizationConfig(**stage1_kwargs)

    # Stage 2 config — load YAML defaults, overlay CLI args
    stage2_kwargs = {
        "n_trials": args.stage2_n_trials,
        "timeout_s": float(args.stage2_timeout),
        "sampler": args.sampler,
        "fold_stride": args.fold_stride,
    }
    try:
        # Source YAML per_asset_* fields as defaults
        stage2_kwargs.setdefault("bound_fraction", opt_config.per_asset_bound_fraction)
        stage2_kwargs.setdefault("regularization_weight", opt_config.per_asset_regularization_weight)
        stage2_kwargs.setdefault("min_bars", opt_config.per_asset_min_bars)
        stage2_kwargs.setdefault("train_bars", opt_config.per_asset_train_bars)
        stage2_kwargs.setdefault("test_bars", opt_config.per_asset_test_bars)
        stage2_kwargs.setdefault("step_bars", opt_config.per_asset_step_bars)
        stage2_kwargs.setdefault("purge_bars", opt_config.per_asset_purge_bars)
        stage2_kwargs.setdefault("validation_drop_threshold", opt_config.per_asset_validation_drop_threshold)
        stage2_kwargs.setdefault("min_zone_count_gate", opt_config.per_asset_min_zone_count_gate)
        stage2_kwargs.setdefault("min_survival_rate_constraint", opt_config.per_asset_min_survival_rate_constraint)
        stage2_kwargs.setdefault("gate_penalty", opt_config.per_asset_gate_penalty)
        stage2_kwargs.setdefault("constraint_penalty_floor", opt_config.per_asset_constraint_penalty_floor)
        stage2_kwargs.setdefault("seed", opt_config.seed)
        stage2_kwargs.setdefault("quality_reversal_threshold_pct", opt_config.quality_reversal_threshold_pct)
        stage2_kwargs.setdefault("quality_coverage_proximity_atr", opt_config.quality_coverage_proximity_atr)
        stage2_kwargs.setdefault("quality_weights", dict(opt_config.quality_weights))
        stage2_kwargs.setdefault("max_lookback", opt_config.per_asset_max_lookback)
    except NameError:
        pass  # opt_config not available if YAML load failed
    # CLI --seed overrides YAML
    if args.seed is not None:
        stage2_kwargs["seed"] = args.seed
    stage2_config = AssetOptimizationConfig(**stage2_kwargs)

    # Universe config
    asset_configs = [
        AssetSRConfig(symbol=a, timeframes=timeframes) for a in assets
    ]
    global_config = raw if raw is not None else {}

    universe_config = UniverseSRConfig(
        assets=asset_configs,
        max_workers=1,
        global_config=global_config,
    )

    return stage1_config, stage2_config, universe_config


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def make_progress_callback(log_interval: int, quiet: bool):
    """Create an Optuna callback that prints trial progress."""
    if quiet:
        return None

    def _callback(study, trial):
        n = trial.number + 1
        if n % log_interval == 0 or n == 1:
            best = study.best_value if study.best_trial else 0.0
            print(f"  Trial {n:>4d} | best: {best:.4f}")

    return _callback


# ---------------------------------------------------------------------------
# Results display
# ---------------------------------------------------------------------------

def auto_output_path(assets: list[str], timeframes: list[str]) -> str:
    """Generate timestamped output path under results/."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    asset_str = "_".join(assets[:3])
    tf_str = "_".join(timeframes[:2])
    filename = f"{asset_str}_{tf_str}_{ts}.json"
    return str(_RESULTS_DIR / filename)


def print_results(result, quiet: bool = False) -> None:
    """Print formatted two-stage optimization results."""
    if quiet:
        return

    meta = result.metadata
    total_time = meta.get("total_time_seconds", 0.0)
    minutes = total_time / 60

    print()
    print("=" * 65)
    print("  S/R TWO-STAGE OPTIMIZATION RESULTS")
    print("=" * 65)
    print(f"  Timestamp: {result.timestamp.isoformat()}")
    print(f"  Total Time: {minutes:.1f} min ({total_time:.0f}s)")
    print()

    # Stage 1
    print("  STAGE 1: GLOBAL OPTIMIZATION")
    print(f"    Best Score:  {result.global_score:.4f}")
    print(f"    Trials:      {meta.get('stage1_n_trials', '?')}")
    print()
    print("    Best Parameters:")
    for key, value in sorted(result.global_params.items()):
        if isinstance(value, float):
            print(f"      {key}: {value:.6f}")
        else:
            print(f"      {key}: {value}")
    print()

    # Stage 2
    s2_optimized = meta.get("stage2_assets_optimized", 0)
    s2_accepted = meta.get("stage2_assets_accepted", 0)
    s2_total = meta.get("stage2_assets_total", 0)
    skipped = meta.get("stage2_assets_skipped", [])

    print("  STAGE 2: PER-ASSET OPTIMIZATION")
    print(f"    Assets optimized: {s2_optimized}/{s2_total}")
    print(f"    Assets accepted:  {s2_accepted}/{s2_optimized}")
    if skipped:
        print(f"    Skipped (insufficient data): {', '.join(skipped)}")
    print()

    if result.per_asset_results:
        print(f"    {'Asset':<12} {'TF':<5} {'Train':>7} {'Val':>7} {'Status':<10} {'Folds':>5}")
        print(f"    {'-'*12} {'-'*5} {'-'*7} {'-'*7} {'-'*10} {'-'*5}")
        for r in result.per_asset_results:
            status = "accepted" if r.accepted else ("fallback" if r.fallback_to_global else "rejected")
            print(
                f"    {r.asset:<12} {r.timeframe:<5} "
                f"{r.train_score:>7.4f} {r.val_score:>7.4f} "
                f"{status:<10} {r.n_folds:>5d}"
            )

    print("=" * 65)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    """Entry point."""
    args = parse_args(argv)

    # Logging
    if not args.quiet:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )

    assets = [a.strip() for a in args.assets.split(",")]
    timeframes = [t.strip() for t in args.timeframes.split(",")]

    # 1. Fetch data
    from app.sr.scripts._utils import fetch_multi_asset_data

    try:
        if not args.quiet:
            print(f"\nFetching data for {assets} × {timeframes}...")
        data_map = fetch_multi_asset_data(
            assets, timeframes,
            lookback_days=args.lookback,
            start_date=args.start_date,
            end_date=args.end_date,
            quiet=args.quiet,
        )
    except Exception as exc:
        print(f"ERROR: Failed to fetch data: {exc}", file=sys.stderr)
        return 1

    # 2. Build configs
    stage1_config, stage2_config, universe_config = build_configs(args)

    # 3. Validate minimum bars
    min_bars = stage2_config.min_bars
    for asset, tf_data in data_map.items():
        for tf, df in tf_data.items():
            if len(df) < min_bars:
                print(
                    f"ERROR: {asset}/{tf} has {len(df)} bars, need at least {min_bars}",
                    file=sys.stderr,
                )
                return 1

    # 4. Set up status writer
    from app.sr.scripts.status_writer import SRStatusFileWriter

    status_writer = SRStatusFileWriter(
        _RESULTS_DIR, assets, timeframes, args.n_trials, args.stage2_n_trials,
    )

    # 5. Run optimization
    if not args.quiet:
        print(
            f"\nStarting optimization: {assets} × {timeframes} "
            f"| Stage 1: {args.n_trials} trials, {args.timeout}s "
            f"| Stage 2: {args.stage2_n_trials} trials/asset, {args.stage2_timeout}s"
        )
        print(f"Status file: {status_writer.status_path}\n")

    from app.sr.optimization.two_stage_optimizer import TwoStageOptimizer

    # Build Optuna callbacks that update the status file + print progress
    progress_cb = make_progress_callback(args.log_interval, args.quiet)

    def _stage1_callback(study, trial):
        best = study.best_value if study.best_trial else 0.0
        status_writer.update_stage1(
            trial_current=trial.number + 1,
            best_score=best,
            best_params=study.best_params if study.best_trial else None,
        )
        if progress_cb is not None:
            progress_cb(study, trial)

    def _stage2_callback(study, trial):
        best = study.best_value if study.best_trial else 0.0
        status_writer.update_stage2(
            asset=_current_s2_asset,
            timeframe=_current_s2_tf,
            trial_current=trial.number + 1,
            best_score=best,
        )

    _current_s2_asset = ""
    _current_s2_tf = ""

    def _on_stage2_start(asset, tf):
        nonlocal _current_s2_asset, _current_s2_tf
        _current_s2_asset = asset
        _current_s2_tf = tf
        status_writer.start_stage2(asset, tf)
        if not args.quiet:
            print(f"\n  Stage 2: {asset}/{tf}...")

    def _on_stage2_complete(asset, tf, result):
        status_writer.complete_stage2(asset, tf)
        if not args.quiet:
            status = "accepted" if result.accepted else "fallback"
            print(f"  Stage 2: {asset}/{tf} → {status} (train={result.train_score:.4f})")

    try:
        optimizer = TwoStageOptimizer(
            universe_config=universe_config,
            stage1_config=stage1_config,
            stage2_config=stage2_config,
        )
        result = optimizer.optimize(
            data_map,
            stage1_callbacks=[_stage1_callback],
            stage2_callbacks=[_stage2_callback],
            on_stage2_start=_on_stage2_start,
            on_stage2_complete=_on_stage2_complete,
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
    output_path = args.output or auto_output_path(assets, timeframes)
    try:
        result.save(output_path)
        if not args.quiet:
            print(f"\nResults saved to: {output_path}")
    except Exception as exc:
        print(f"WARNING: Could not save results: {exc}", file=sys.stderr)

    # 8. Apply best params to YAML (--apply / --dry-run)
    if args.apply:
        yaml_path = args.config or str(_DEFAULT_YAML)
        if args.dry_run:
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".yaml", delete=False,
                ) as tmp_f:
                    tmp_path = tmp_f.name
                shutil.copy2(yaml_path, tmp_path)
                result.apply_to_yaml(tmp_path, backup=False)
                with open(yaml_path) as f:
                    original_lines = f.readlines()
                with open(tmp_path) as f:
                    modified_lines = f.readlines()
                diff = difflib.unified_diff(
                    original_lines, modified_lines,
                    fromfile=yaml_path, tofile=yaml_path + " (optimized)",
                )
                diff_str = "".join(diff)
                if diff_str:
                    print("\n--- DRY RUN: YAML diff ---")
                    print(diff_str)
                else:
                    print("\n--- DRY RUN: no changes ---")
            finally:
                os.unlink(tmp_path)
        else:
            try:
                result.apply_to_yaml(yaml_path)
                if not args.quiet:
                    print(f"Best params written to: {yaml_path}")
            except Exception as exc:
                print(f"WARNING: Could not apply params to YAML: {exc}", file=sys.stderr)

    # 9. Exit code
    meta = result.metadata
    accepted = meta.get("stage2_assets_accepted", 0)
    optimized = meta.get("stage2_assets_optimized", 0)
    if optimized == 0:
        return 0 if result.global_score > 0 else 1
    accept_rate = accepted / optimized
    return 0 if accept_rate > _MIN_ACCEPT_RATE else 1


if __name__ == "__main__":
    sys.exit(main())
