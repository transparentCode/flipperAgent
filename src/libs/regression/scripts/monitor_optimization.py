#!/usr/bin/env python3
"""
Regression Optimization Monitor CLI (V2 MOTPE).

Inspect, list, watch, and compare optimization result files.

Usage:
    python app/regression/scripts/monitor_optimization.py show <path>
    python app/regression/scripts/monitor_optimization.py list
    python app/regression/scripts/monitor_optimization.py watch [--interval 5]
    python app/regression/scripts/monitor_optimization.py compare <path1> <path2>
    python app/regression/scripts/monitor_optimization.py --help
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from app.regression.optimization.models import (
    RegressionOptimizationResult,
)

_RESULTS_DIR = Path(__file__).parent.parent / "optimization" / "results"
_STATUS_FILE = _RESULTS_DIR / ".optimization_status.json"


def parse_args(argv=None):
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Monitor and inspect regression optimization results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Show a result file
    python app/regression/scripts/monitor_optimization.py show optimization/results/BTCUSDT_1h_20260414.json

    # List all results
    python app/regression/scripts/monitor_optimization.py list

    # Watch a result file for updates (during a run)
    python app/regression/scripts/monitor_optimization.py watch optimization/results/BTCUSDT_1h_20260414.json

    # Compare two runs
    python app/regression/scripts/monitor_optimization.py compare run1.json run2.json
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # -- show --
    show_parser = subparsers.add_parser("show", help="Display detailed results from a file")
    show_parser.add_argument("path", type=str, help="Path to result JSON")

    # -- list --
    list_parser = subparsers.add_parser("list", help="List all result files")
    list_parser.add_argument(
        "--sort",
        choices=["time", "score", "asset"],
        default="time",
        help="Sort order (default: time)",
    )

    # -- watch --
    watch_parser = subparsers.add_parser(
        "watch", help="Watch live optimization progress via status file",
    )
    watch_parser.add_argument(
        "--status-file",
        type=str,
        default=str(_STATUS_FILE),
        help=f"Path to status JSON (default: {_STATUS_FILE.name})",
    )
    watch_parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="Poll interval in seconds (default: 5)",
    )

    # -- compare --
    compare_parser = subparsers.add_parser("compare", help="Compare two result files")
    compare_parser.add_argument("path1", type=str, help="First result JSON")
    compare_parser.add_argument("path2", type=str, help="Second result JSON")

    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

def cmd_show(path: str) -> int:
    """Display detailed results from a single file."""
    try:
        result = RegressionOptimizationResult.load(path)
    except FileNotFoundError:
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: Failed to load {path}: {exc}", file=sys.stderr)
        return 1

    b = result.best_benchmarks
    gate_rate = (
        result.n_trials_passed_gate / result.n_trials_total * 100
        if result.n_trials_total > 0 else 0.0
    )
    minutes = result.total_time_seconds / 60

    print("=" * 65)
    print("  REGRESSION OPTIMIZATION RESULT (V2 MOTPE)")
    print("=" * 65)
    print(f"  File:      {path}")
    print(f"  Asset:     {result.asset}")
    print(f"  Timeframe: {result.timeframe}")
    print(f"  Timestamp: {result.timestamp.isoformat()}")
    print()
    obj_vals = result.best_objective_values
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
    print()
    print("  CONFIG")
    print(f"    Seed:     {result.config.seed}")
    print(f"    Trials:   {result.config.n_trials}")
    print(f"    Timeout:  {result.config.timeout_seconds}s")
    print(f"    Tier:     {result.config.optimization_tier}")
    print("=" * 65)
    return 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def _load_result_summary(path: Path) -> dict | None:
    """Load minimal fields from a result JSON without full deserialization."""
    try:
        with open(path) as f:
            data = json.load(f)
        obj_vals = data.get("best_objective_values", [0.0, 0.0, 0.0])
        return {
            "file": path.name,
            "asset": data.get("asset", "?"),
            "timeframe": data.get("timeframe", "?"),
            "best_objective_values": obj_vals,
            "best_dir": obj_vals[0] if len(obj_vals) > 0 else 0.0,
            "best_cov": obj_vals[1] if len(obj_vals) > 1 else 0.0,
            "best_sharpe": obj_vals[2] if len(obj_vals) > 2 else 0.0,
            "n_trials_total": data.get("n_trials_total", 0),
            "n_trials_passed_gate": data.get("n_trials_passed_gate", 0),
            "total_time_seconds": data.get("total_time_seconds", 0.0),
            "timestamp": data.get("timestamp", ""),
        }
    except Exception:
        return None


def cmd_list(sort_by: str = "time") -> int:
    """List all result files in the results directory."""
    if not _RESULTS_DIR.exists():
        print(f"No results directory: {_RESULTS_DIR}")
        return 0

    json_files = sorted(_RESULTS_DIR.glob("*.json"))
    if not json_files:
        print("No result files found.")
        return 0

    summaries = []
    for p in json_files:
        s = _load_result_summary(p)
        if s:
            summaries.append(s)

    if sort_by == "score":
        summaries.sort(key=lambda s: s["best_sharpe"], reverse=True)
    elif sort_by == "asset":
        summaries.sort(key=lambda s: (s["asset"], s["timeframe"]))
    else:  # time
        summaries.sort(key=lambda s: s["timestamp"], reverse=True)

    # Header
    print(f"{'File':<40} {'Asset':<10} {'TF':<5} {'Dir':>6} {'Cov':>6} {'Shp':>6} {'Trials':>7} {'Gate%':>6} {'Time':>7}")
    print("-" * 100)

    for s in summaries:
        gate_pct = (
            s["n_trials_passed_gate"] / s["n_trials_total"] * 100
            if s["n_trials_total"] > 0 else 0.0
        )
        time_min = s["total_time_seconds"] / 60
        print(
            f"{s['file']:<40} {s['asset']:<10} {s['timeframe']:<5} "
            f"{s['best_dir']:>6.3f} {s['best_cov']:>6.3f} {s['best_sharpe']:>6.3f} "
            f"{s['n_trials_total']:>7d} "
            f"{gate_pct:>5.1f}% {time_min:>6.1f}m"
        )

    print(f"\n{len(summaries)} result(s) in {_RESULTS_DIR}")
    return 0


# ---------------------------------------------------------------------------
# watch
# ---------------------------------------------------------------------------

def _check_process_alive(pid) -> bool:
    """Check if optimizer PID is still running."""
    if not isinstance(pid, int):
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _read_status(path: str) -> dict | None:
    """Safely read status JSON. Returns None if missing or invalid."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable string."""
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {secs:02d}s"


def cmd_watch(status_file: str, interval: int = 5) -> int:
    """Watch live optimization progress via the status file.

    The optimizer writes ``.optimization_status.json`` atomically on every
    trial completion.  This command polls that file and displays a
    real-time dashboard.
    """
    print()
    print("  ======================================")
    print("    Regression Optimization Monitor")
    print("  ======================================")
    print(f"  Watching: {status_file}")
    print(f"  Polling every {interval}s  (Ctrl+C to stop)")
    print()

    last_status: dict | None = None

    try:
        while True:
            s = _read_status(status_file)

            if s is None:
                print(f"\r  Waiting for status file ...", end="", flush=True)
                time.sleep(interval)
                continue

            # Detect stale file from a previous run
            pid = s.get("pid")
            if last_status is None and not _check_process_alive(pid):
                st = s.get("status", "?")
                print(f"  Stale status file (PID {pid}, status={st}). Waiting for new optimizer...\n")
                time.sleep(interval)
                continue

            status = s.get("status", "unknown").upper()
            asset = s.get("asset", "?")
            tf = s.get("timeframe", "?")
            trial_cur = s.get("trial_current", 0)
            trial_total = s.get("n_trials_target", 0)
            obj_vals = s.get("best_objective_values", [])
            gate = s.get("n_trials_passed_gate", 0)
            pruned = s.get("n_trials_pruned", 0)

            # Format objectives
            if obj_vals and len(obj_vals) >= 3:
                obj_str = f"dir={obj_vals[0]:.3f} cov={obj_vals[1]:.3f} shp={obj_vals[2]:.3f}"
            elif obj_vals:
                obj_str = ", ".join(f"{v:.3f}" for v in obj_vals)
            else:
                obj_str = "pending..."

            # Progress bar
            pct = (trial_cur / trial_total * 100) if trial_total > 0 else 0.0
            bar_len = 30
            filled = int(bar_len * pct / 100)
            bar = "=" * filled + "-" * (bar_len - filled)

            # Elapsed + ETA
            start_str = s.get("start_time", "")
            elapsed_str = "?"
            eta_str = "calculating..."
            if start_str:
                try:
                    start_dt = datetime.fromisoformat(start_str)
                    elapsed = (datetime.now() - start_dt).total_seconds()
                    elapsed_str = _format_duration(elapsed)
                    if trial_cur >= 3:
                        rate = trial_cur / max(elapsed, 1.0)
                        remaining = (trial_total - trial_cur) / max(rate, 0.001)
                        eta_str = f"~{_format_duration(remaining)}"
                except Exception:
                    pass

            # Process alive
            alive = _check_process_alive(pid) if isinstance(pid, int) else None
            alive_str = "alive" if alive else ("DEAD" if alive is False else "?")

            # Update time
            update_str = "?"
            last_upd = s.get("last_update", "")
            if last_upd:
                try:
                    update_str = datetime.fromisoformat(last_upd).strftime("%H:%M:%S")
                except Exception:
                    pass

            gate_pct = gate / trial_cur * 100 if trial_cur > 0 else 0.0
            pruned_str = f"  Pruned:    {pruned}\n" if pruned else ""

            output = (
                f"\r\033[K"
                f"\n  Asset:     {asset} {tf}\n"
                f"  Status:    {status}\n"
                f"\n"
                f"  Progress:  [{bar}] {trial_cur}/{trial_total} ({pct:.1f}%)\n"
                f"  Best:      {obj_str}\n"
                f"  Gate:      {gate}/{trial_cur} ({gate_pct:.1f}%)\n"
                f"{pruned_str}"
                f"  ETA:       {eta_str}\n"
                f"  Elapsed:   {elapsed_str}\n"
                f"\n"
                f"  Process:   PID {pid} ({alive_str})\n"
                f"  Updated:   {update_str}\n"
                f"  {'='*38}\n"
            )

            # Count lines for cursor-up (overwrite previous)
            n_lines = output.count("\n")
            if last_status is not None:
                sys.stdout.write(f"\033[{n_lines}A")
            sys.stdout.write(output)
            sys.stdout.flush()

            # Terminal states
            if s.get("status") == "completed":
                best_params = s.get("best_params", {})
                print(f"\n  COMPLETED — Best: {obj_str}")
                if best_params:
                    print("  Best params:")
                    for k, v in best_params.items():
                        print(f"    {k}: {v}")
                return 0
            if s.get("status") == "failed":
                print(f"\n  FAILED — {s.get('error', 'unknown error')}")
                return 1

            # Process died without updating status
            if isinstance(pid, int) and not _check_process_alive(pid):
                print(f"\n  WARNING: PID {pid} is no longer running. Optimizer may have crashed.")
                return 3

            last_status = s
            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\n  Monitor stopped by user.")
    return 0


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------

def cmd_compare(path1: str, path2: str) -> int:
    """Compare two result files side-by-side."""
    try:
        r1 = RegressionOptimizationResult.load(path1)
        r2 = RegressionOptimizationResult.load(path2)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: Failed to load results: {exc}", file=sys.stderr)
        return 1

    name1 = Path(path1).name
    name2 = Path(path2).name

    print("=" * 75)
    print("  REGRESSION OPTIMIZATION COMPARISON")
    print("=" * 75)
    print(f"  {'':30s} {'Run A':>20s} {'Run B':>20s}")
    print(f"  {'File':30s} {name1:>20s} {name2:>20s}")
    print(f"  {'Asset':30s} {r1.asset:>20s} {r2.asset:>20s}")
    print(f"  {'Timeframe':30s} {r1.timeframe:>20s} {r2.timeframe:>20s}")
    print()

    # Scores
    print("  SCORES")
    obj1 = r1.best_objective_values
    obj2 = r2.best_objective_values
    _compare_row("Direction Accuracy", obj1[0], obj2[0])
    _compare_row("Band Coverage", obj1[1], obj2[1])
    _compare_row("Confidence Sharpe", obj1[2], obj2[2])
    _compare_row("Trials", r1.n_trials_total, r2.n_trials_total, fmt="d")
    _compare_row("Gate Passed", r1.n_trials_passed_gate, r2.n_trials_passed_gate, fmt="d")

    gate1 = r1.n_trials_passed_gate / r1.n_trials_total * 100 if r1.n_trials_total else 0
    gate2 = r2.n_trials_passed_gate / r2.n_trials_total * 100 if r2.n_trials_total else 0
    _compare_row("Gate Rate %", gate1, gate2, fmt=".1f")
    _compare_row("Time (s)", r1.total_time_seconds, r2.total_time_seconds, fmt=".0f")
    print()

    # Benchmarks
    b1, b2 = r1.best_benchmarks, r2.best_benchmarks
    print("  BENCHMARKS")
    _compare_row("T1 Direction Acc", b1.weighted_direction_score, b2.weighted_direction_score)
    _compare_row("T2 Band Coverage %", b1.band_coverage_pct * 100, b2.band_coverage_pct * 100, fmt=".2f")
    _compare_row("T2 Band Stability", b1.band_width_stability, b2.band_width_stability)
    _compare_row("T3 Durbin-Watson", b1.durbin_watson, b2.durbin_watson, fmt=".3f")
    _compare_row("T4 Confidence Rho", b1.confidence_return_spearman, b2.confidence_return_spearman)
    _compare_row("T5 Confidence Sharpe", b1.confidence_sharpe, b2.confidence_sharpe)
    _compare_row("T5 Sharpe Improv", b1.sharpe_improvement, b2.sharpe_improvement)
    print()

    # Params diff
    all_keys = sorted(set(r1.best_params) | set(r2.best_params))
    if all_keys:
        print("  PARAMETER DIFF")
        for key in all_keys:
            v1 = r1.best_params.get(key)
            v2 = r2.best_params.get(key)
            changed = v1 != v2
            marker = " *" if changed else ""
            v1_str = _fmt_param(v1)
            v2_str = _fmt_param(v2)
            print(f"    {key:30s} {v1_str:>20s} {v2_str:>20s}{marker}")
        print()
        print("  * = changed between runs")

    print("=" * 75)
    return 0


def _compare_row(label: str, v1, v2, fmt: str = ".4f"):
    """Print a comparison row with delta."""
    if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
        delta = v2 - v1
        sign = "+" if delta >= 0 else ""
        f1 = f"{v1:{fmt}}"
        f2 = f"{v2:{fmt}}"
        fd = f"{sign}{delta:{fmt}}"
        print(f"    {label:30s} {f1:>20s} {f2:>20s}  ({fd})")
    else:
        print(f"    {label:30s} {str(v1):>20s} {str(v2):>20s}")


def _fmt_param(v) -> str:
    """Format a parameter value for display."""
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.6f}"
    return str(v)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    """Entry point."""
    args = parse_args(argv)

    if args.command is None:
        parse_args(["--help"])
        return 1

    if args.command == "show":
        return cmd_show(args.path)
    elif args.command == "list":
        return cmd_list(args.sort)
    elif args.command == "watch":
        return cmd_watch(args.status_file, args.interval)
    elif args.command == "compare":
        return cmd_compare(args.path1, args.path2)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
