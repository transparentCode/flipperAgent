#!/usr/bin/env python3
"""
Sobol Sensitivity Analysis for SR Optimizer Parameters
=======================================================
Runs quasi-random Sobol samples across the Stage 1 parameter space,
evaluates each via MultiBarRunner + ZoneQualityEvaluator, and computes
first-order (S1) and total-order (ST) Sobol sensitivity indices.

This tells you which parameters actually drive output variance and which
are inert — enabling informed parameter tiering for Phase 1.

Usage:
    python app/sr/scripts/sobol_sensitivity.py -a ETHUSDT -t 1h -N 64
    python app/sr/scripts/sobol_sensitivity.py -a ETHUSDT -t 1h -N 128 \
        --start-date 2024-01-01 --end-date 2026-01-01
    python app/sr/scripts/sobol_sensitivity.py --help

N must be a power of 2 for Saltelli sampling.
Total evaluations = N × (2D + 2) where D = number of parameters.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

logger = logging.getLogger("app.sr.scripts.sobol_sensitivity")

_DEFAULT_YAML = Path(__file__).parent.parent / "config" / "sr.yaml"

# Stage 2-only params excluded from global Sobol analysis
_STAGE2_ONLY = frozenset({
    "pipeline.min_emit_strength",
    "pipeline.max_new_zones_per_bar",
})


# ---------------------------------------------------------------------------
# Parameter space definition
# ---------------------------------------------------------------------------

def _build_problem() -> dict:
    """Build the SALib problem dict from the Stage 1 parameter space.

    Returns dict with keys: 'num_vars', 'names', 'bounds', 'kinds'.
    'kinds' is not part of SALib but we keep it for int rounding.
    """
    from app.sr.optimization._shared import default_parameter_space

    space = default_parameter_space()
    names: List[str] = []
    bounds: List[List[float]] = []
    kinds: List[str] = []

    for name, spec in space.items():
        if name in _STAGE2_ONLY:
            continue
        if not spec.enabled:
            continue
        names.append(name)
        bounds.append([float(spec.low), float(spec.high)])
        kinds.append(spec.kind)

    return {
        "num_vars": len(names),
        "names": names,
        "bounds": bounds,
        "kinds": kinds,
    }


def _params_from_sample(
    sample: np.ndarray,
    names: List[str],
    kinds: List[str],
) -> Dict[str, float]:
    """Convert a single Saltelli sample row into an optimizer params dict."""
    params: Dict[str, float] = {}
    for i, name in enumerate(names):
        val = sample[i]
        if kinds[i] == "int":
            val = int(round(val))
        params[name] = val
    return params


# ---------------------------------------------------------------------------
# Single evaluation
# ---------------------------------------------------------------------------

def _evaluate_params(
    params: Dict[str, float],
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    raw_config: Dict[str, Any],
    characteristics: Any,
    eval_bars: int = 2000,
) -> Dict[str, float]:
    """Run the pipeline with given params and return all metric scores.

    Returns dict with keys: composite, survival_rate, touch_accuracy,
    false_breakout_rate, strength_stability, coverage.
    """
    from app.sr.config_resolver import SRConfigResolver
    from app.sr.optimization.multi_bar_runner import MultiBarRunner
    from app.sr.optimization.quality_metrics import ZoneQualityEvaluator
    from app.sr.pipeline import SRv2Pipeline

    # Build nested overrides from flat dotted params
    overrides: Dict[str, Any] = {}
    for param_name, value in params.items():
        parts = param_name.split(".")
        cursor = overrides
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value

    # Merge into config
    config = copy.deepcopy(raw_config)
    sr_section = config.get("sr", {})

    from app.sr.optimization._shared import deep_merge

    config["sr"] = deep_merge(sr_section, overrides)

    # Also inject overrides into the per-asset/tf section so they
    # take highest priority in the resolver cascade
    # (global → per_tf → per-asset-defaults → per-asset/tf).
    asset_tf = (
        config
        .setdefault("assets", {})
        .setdefault(asset, {})
        .setdefault(timeframe, {})
    )
    for section_key, section_val in overrides.items():
        if isinstance(section_val, dict):
            asset_tf[section_key] = deep_merge(
                asset_tf.get(section_key, {}), section_val,
            )
        else:
            asset_tf[section_key] = section_val

    resolver = SRConfigResolver()
    resolved = resolver.resolve(
        asset, timeframe, config,
        characteristics=characteristics,
    )
    pipeline = SRv2Pipeline(resolved, asset=asset, timeframe=timeframe)

    eval_df = df.iloc[-eval_bars:] if len(df) > eval_bars else df
    runner = MultiBarRunner(pipeline)
    run_result = runner.run(eval_df)

    evaluator = ZoneQualityEvaluator()
    metrics = evaluator.evaluate(run_result)
    composite = evaluator.composite_score(metrics)

    return {
        "composite": composite,
        "survival_rate": metrics.survival_rate,
        "touch_accuracy": metrics.touch_accuracy,
        "false_breakout_rate": metrics.false_breakout_rate,
        "strength_stability": metrics.strength_stability,
        "coverage": metrics.coverage,
    }


# ---------------------------------------------------------------------------
# Sobol runner
# ---------------------------------------------------------------------------

def run_sobol(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    raw_config: Dict[str, Any],
    characteristics: Any,
    n_samples: int = 64,
    eval_bars: int = 2000,
    quiet: bool = False,
) -> Dict[str, Any]:
    """Run full Sobol sensitivity analysis.

    Parameters
    ----------
    n_samples : int
        Base sample count (must be power of 2).
        Total evaluations = n_samples × (2D + 2).

    Returns
    -------
    dict with keys:
        problem: SALib problem dict
        results: {metric_name: SALib analysis result}
        raw_outputs: np.ndarray of shape (total_evals, n_metrics)
        sample_params: list of param dicts
        eval_time_s: total wall-clock seconds
    """
    from SALib.sample import sobol as sobol_sample
    from SALib.analyze import sobol as sobol_analyze

    problem = _build_problem()
    D = problem["num_vars"]
    kinds = problem.pop("kinds")  # SALib doesn't know about 'kinds'

    if not quiet:
        total_evals = n_samples * (D + 2)
        print(f"\nSobol analysis: {D} params, N={n_samples}")
        print(f"  Total evaluations: {total_evals}")
        print(f"  Eval bars per sample: {eval_bars}")
        est_per_eval = 3.0  # rough seconds per eval
        print(f"  Estimated time: ~{total_evals * est_per_eval / 60:.0f} min")
        print()

    # Generate Sobol (Saltelli) samples
    param_values = sobol_sample.sample(problem, n_samples, calc_second_order=False)
    total_evals = len(param_values)

    if not quiet:
        print(f"  Generated {total_evals} Saltelli samples")

    # Evaluate each sample
    metric_names = [
        "composite", "survival_rate", "touch_accuracy",
        "false_breakout_rate", "strength_stability", "coverage",
    ]
    raw_outputs = np.zeros((total_evals, len(metric_names)))

    t0 = time.time()
    failed = 0

    for i in range(total_evals):
        params = _params_from_sample(param_values[i], problem["names"], kinds)
        try:
            scores = _evaluate_params(
                params, df, asset, timeframe,
                raw_config, characteristics, eval_bars,
            )
            for j, mname in enumerate(metric_names):
                raw_outputs[i, j] = scores[mname]
        except Exception as exc:
            logger.warning("Sample %d failed: %s", i, exc)
            failed += 1
            # Use NaN — SALib handles it
            raw_outputs[i, :] = 0.0

        if not quiet and (i + 1) % 10 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            remaining = (total_evals - i - 1) / rate / 60
            print(
                f"\r  Progress: {i + 1}/{total_evals} "
                f"({(i + 1) / total_evals * 100:.0f}%) "
                f"~{remaining:.1f} min remaining   ",
                end="", flush=True,
            )

    elapsed = time.time() - t0
    if not quiet:
        print(f"\n  Completed {total_evals} evaluations in {elapsed / 60:.1f} min")
        if failed:
            print(f"  WARNING: {failed} evaluations failed (replaced with 0)")

    # Analyze each metric
    # Put 'kinds' back for reporting but SALib doesn't need it
    results: Dict[str, Any] = {}
    for j, mname in enumerate(metric_names):
        Y = raw_outputs[:, j]
        # Check for sufficient variance
        if np.std(Y) < 1e-10:
            logger.warning("Metric '%s' has near-zero variance — skipping Sobol", mname)
            results[mname] = {"S1": np.zeros(D), "ST": np.zeros(D), "skipped": True}
            continue
        si = sobol_analyze.analyze(problem, Y, calc_second_order=False, print_to_console=False)
        results[mname] = si

    return {
        "problem": {**problem, "kinds": kinds},
        "results": results,
        "raw_outputs": raw_outputs,
        "metric_names": metric_names,
        "eval_time_s": elapsed,
        "n_samples": n_samples,
        "total_evals": total_evals,
        "failed": failed,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_report(sobol_result: Dict[str, Any]) -> None:
    """Print a formatted sensitivity report."""
    problem = sobol_result["problem"]
    names = problem["names"]
    results = sobol_result["results"]
    metric_names = sobol_result["metric_names"]

    print()
    print("=" * 80)
    print("  SOBOL SENSITIVITY ANALYSIS — RESULTS")
    print("=" * 80)
    print(f"  N={sobol_result['n_samples']}, "
          f"total_evals={sobol_result['total_evals']}, "
          f"time={sobol_result['eval_time_s'] / 60:.1f} min")
    if sobol_result["failed"]:
        print(f"  WARNING: {sobol_result['failed']} evaluations failed")
    print()

    # Per-metric breakdown
    for mname in metric_names:
        si = results[mname]
        if isinstance(si, dict) and si.get("skipped"):
            print(f"  [{mname}] — SKIPPED (near-zero variance)")
            print()
            continue

        S1 = np.array(si["S1"])
        ST = np.array(si["ST"])
        S1_conf = np.array(si["S1_conf"])
        ST_conf = np.array(si["ST_conf"])

        # Sort by ST descending
        order = np.argsort(-ST)

        print(f"  [{mname}]")
        print(f"  {'Parameter':<50s}  {'S1':>6s} ±{'conf':>5s}  {'ST':>6s} ±{'conf':>5s}")
        print(f"  {'-' * 50}  {'-' * 6} {'-' * 6}  {'-' * 6} {'-' * 6}")
        for idx in order:
            s1_val = S1[idx]
            st_val = ST[idx]
            s1_c = S1_conf[idx]
            st_c = ST_conf[idx]
            flag = " ***" if st_val > 0.05 else ""
            print(
                f"  {names[idx]:<50s}  {s1_val:>6.3f} ±{s1_c:>5.3f}  "
                f"{st_val:>6.3f} ±{st_c:>5.3f}{flag}"
            )
        print()

    # Composite-focused summary
    print("=" * 80)
    print("  PARAMETER TIERING RECOMMENDATION (based on composite ST)")
    print("=" * 80)

    si_comp = results.get("composite", {})
    if isinstance(si_comp, dict) and si_comp.get("skipped"):
        print("  Cannot tier — composite had zero variance")
        return

    ST = np.array(si_comp["ST"])
    order = np.argsort(-ST)

    tier_high: List[str] = []
    tier_mid: List[str] = []
    tier_low: List[str] = []

    for idx in order:
        st_val = ST[idx]
        name = names[idx]
        if st_val > 0.05:
            tier_high.append(f"  {name:<50s}  ST={st_val:.3f}")
        elif st_val > 0.01:
            tier_mid.append(f"  {name:<50s}  ST={st_val:.3f}")
        else:
            tier_low.append(f"  {name:<50s}  ST={st_val:.3f}")

    print()
    print(f"  HIGH sensitivity (ST > 0.05) — OPTIMIZE with Optuna:")
    for line in tier_high:
        print(line)
    print()
    print(f"  MEDIUM sensitivity (0.01 < ST < 0.05) — calibrate from backtest:")
    for line in tier_mid:
        print(line)
    print()
    print(f"  LOW sensitivity (ST < 0.01) — FIX to domain defaults:")
    for line in tier_low:
        print(line)
    print()
    print("=" * 80)


def save_results(
    sobol_result: Dict[str, Any],
    output_path: Path,
) -> None:
    """Save Sobol results to JSON for later analysis."""
    serializable = {
        "problem": sobol_result["problem"],
        "metric_names": sobol_result["metric_names"],
        "n_samples": sobol_result["n_samples"],
        "total_evals": sobol_result["total_evals"],
        "eval_time_s": sobol_result["eval_time_s"],
        "failed": sobol_result["failed"],
        "results": {},
        "raw_outputs_shape": list(sobol_result["raw_outputs"].shape),
    }

    for mname, si in sobol_result["results"].items():
        if isinstance(si, dict) and si.get("skipped"):
            serializable["results"][mname] = {"skipped": True}
            continue
        serializable["results"][mname] = {
            "S1": [float(x) for x in si["S1"]],
            "ST": [float(x) for x in si["ST"]],
            "S1_conf": [float(x) for x in si["S1_conf"]],
            "ST_conf": [float(x) for x in si["ST_conf"]],
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(serializable, f, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sobol sensitivity analysis for SR optimizer parameters",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-a", "--asset", default="ETHUSDT", help="Trading pair")
    parser.add_argument("-t", "--timeframe", default="1h", help="Timeframe")
    parser.add_argument(
        "-N", "--n-samples", type=int, default=64,
        help="Base Sobol sample count (power of 2). Total evals = N×(2D+2)",
    )
    parser.add_argument(
        "--eval-bars", type=int, default=2000,
        help="Trailing bars per evaluation (default: 2000)",
    )
    parser.add_argument(
        "--start-date", type=str, default=None,
        help="Start date (YYYY-MM-DD). Overrides default lookback.",
    )
    parser.add_argument(
        "--end-date", type=str, default=None,
        help="End date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "-l", "--lookback", type=int, default=90,
        help="Lookback days (default: 90). Ignored if --start-date set.",
    )
    parser.add_argument(
        "-o", "--output", type=str, default=None,
        help="Output JSON path (default: app/sr/optimization/results/sobol_<asset>_<tf>.json)",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress progress")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    if not args.quiet:
        logging.basicConfig(
            level=logging.WARNING,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )
    else:
        logging.basicConfig(level=logging.ERROR)

    # Suppress noisy SR pipeline debug logs regardless
    logging.getLogger("app.sr").setLevel(logging.WARNING)
    logging.getLogger("app.sr.pipeline").setLevel(logging.WARNING)
    logging.getLogger("app.sr.regime_gate").setLevel(logging.WARNING)

    # 1. Fetch data
    from app.sr.scripts._utils import fetch_data, build_characteristics

    try:
        if not args.quiet:
            print(f"\nFetching {args.asset} {args.timeframe}...")
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

    if len(df) < 200:
        print(f"ERROR: Need at least 200 bars, got {len(df)}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(f"  {len(df)} bars loaded")

    # 2. Resolve base config + characteristics
    from app.sr.config_resolver import SRConfigResolver
    from app.utils.ConfigLoader import ConfigLoader

    raw_config = ConfigLoader.load(str(_DEFAULT_YAML)) if _DEFAULT_YAML.exists() else {}
    resolver = SRConfigResolver()
    base_resolved = resolver.resolve(args.asset, args.timeframe, raw_config)
    characteristics = build_characteristics(
        df, args.asset, args.timeframe,
        metadata=base_resolved.metadata,
    )

    # 3. Run Sobol analysis
    sobol_result = run_sobol(
        df, args.asset, args.timeframe,
        raw_config, characteristics,
        n_samples=args.n_samples,
        eval_bars=args.eval_bars,
        quiet=args.quiet,
    )

    # 4. Print report
    print_report(sobol_result)

    # 5. Save results
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = (
            Path(__file__).parent.parent
            / "optimization" / "results"
            / f"sobol_{args.asset}_{args.timeframe}.json"
        )
    save_results(sobol_result, output_path)
    if not args.quiet:
        print(f"  Results saved to {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
