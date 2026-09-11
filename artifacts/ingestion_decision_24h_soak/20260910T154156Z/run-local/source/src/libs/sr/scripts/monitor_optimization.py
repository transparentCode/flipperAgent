#!/usr/bin/env python3
"""
S/R Optimization Monitor CLI.

Inspect, list, watch, and compare SR optimization result files.

Usage:
    python app/sr/scripts/monitor_optimization.py show <path>
    python app/sr/scripts/monitor_optimization.py list [--sort time|score|asset]
    python app/sr/scripts/monitor_optimization.py watch [--interval 5]
    python app/sr/scripts/monitor_optimization.py compare <path1> <path2>
    python app/sr/scripts/monitor_optimization.py --help
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from app.sr.optimization._shared import RESULTS_DIR as _RESULTS_DIR
_STATUS_FILE = _RESULTS_DIR / ".optimization_status.json"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Monitor and inspect SR optimization results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python app/sr/scripts/monitor_optimization.py show results/BTCUSDT_1h_20260429.json
    python app/sr/scripts/monitor_optimization.py list --sort score
    python app/sr/scripts/monitor_optimization.py watch --interval 3
    python app/sr/scripts/monitor_optimization.py compare run1.json run2.json
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # -- show --
    show_parser = subparsers.add_parser("show", help="Display detailed results")
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
        "watch", help="Watch live optimization progress",
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
# Helpers
# ---------------------------------------------------------------------------

def _load_result_json(path: str) -> dict:
    """Load and return raw result JSON dict."""
    with open(path) as f:
        return json.load(f)


def _load_result_summary(path: Path) -> dict | None:
    """Load minimal fields from a result JSON without full deserialization."""
    try:
        with open(path) as f:
            data = json.load(f)
        meta = data.get("metadata", {})
        assets = list(data.get("per_asset_params", {}).keys())
        return {
            "file": path.name,
            "assets": ",".join(assets) if assets else "?",
            "global_score": data.get("global_score", 0.0),
            "n_asset_results": len(data.get("per_asset_results", [])),
            "total_time_seconds": meta.get("total_time_seconds", 0.0),
            "timestamp": data.get("timestamp", ""),
        }
    except Exception:
        return None


def _fmt_param(v) -> str:
    """Format a parameter value for display."""
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.6f}"
    return str(v)


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


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable string."""
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {secs:02d}s"


def _load_s2_trials_from_config() -> int:
    """Try to read per_asset_n_trials from sr.yaml as fallback.

    Returns 0 if the config cannot be loaded (non-fatal).
    """
    try:
        import yaml
        config_path = Path(__file__).parent.parent / "config" / "sr.yaml"
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        return int(
            cfg.get("sr", {}).get("optimization", {}).get("per_asset_n_trials", 0)
        )
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

def cmd_show(path: str) -> int:
    """Display detailed results from a single file."""
    try:
        data = _load_result_json(path)
    except FileNotFoundError:
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: Failed to load {path}: {exc}", file=sys.stderr)
        return 1

    meta = data.get("metadata", {})
    total_time = meta.get("total_time_seconds", 0.0)
    minutes = total_time / 60

    print("=" * 65)
    print("  S/R OPTIMIZATION RESULT")
    print("=" * 65)
    print(f"  File:      {path}")
    print(f"  Timestamp: {data.get('timestamp', '?')}")
    print(f"  Total Time: {minutes:.1f} min ({total_time:.0f}s)")
    print()

    # Stage 1
    print("  STAGE 1: GLOBAL")
    print(f"    Score:  {data.get('global_score', 0.0):.4f}")
    print(f"    Trials: {meta.get('stage1_n_trials', '?')}")
    print()

    global_params = data.get("global_params", {})
    if global_params:
        print("    Parameters:")
        for key, value in sorted(global_params.items()):
            print(f"      {key}: {_fmt_param(value)}")
        print()

    # Stage 2
    per_asset_results = data.get("per_asset_results", [])
    s2_optimized = meta.get("stage2_assets_optimized", len(per_asset_results))
    s2_accepted = meta.get("stage2_assets_accepted", 0)

    print("  STAGE 2: PER-ASSET")
    print(f"    Optimized: {s2_optimized}")
    print(f"    Accepted:  {s2_accepted}")
    print()

    if per_asset_results:
        print(f"    {'Asset':<12} {'TF':<5} {'Train':>7} {'Val':>7} {'Status':<10} {'Folds':>5} {'Gates':>5} {'Const':>5}")
        print(f"    {'-'*12} {'-'*5} {'-'*7} {'-'*7} {'-'*10} {'-'*5} {'-'*5} {'-'*5}")
        for r in per_asset_results:
            status = "accepted" if r.get("accepted") else (
                "fallback" if r.get("fallback_to_global") else "rejected"
            )
            print(
                f"    {r.get('asset', '?'):<12} {r.get('timeframe', '?'):<5} "
                f"{r.get('train_score', 0.0):>7.4f} {r.get('val_score', 0.0):>7.4f} "
                f"{status:<10} {r.get('n_folds', 0):>5d} "
                f"{r.get('gate_failures', 0):>5d} {r.get('constraint_failures', 0):>5d}"
            )

    print("=" * 65)
    return 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def cmd_list(sort_by: str = "time") -> int:
    """List all result files in the results directory."""
    if not _RESULTS_DIR.exists():
        print(f"No results directory: {_RESULTS_DIR}")
        return 0

    json_files = sorted(
        p for p in _RESULTS_DIR.glob("*.json")
        if not p.name.startswith(".")
    )
    if not json_files:
        print("No result files found.")
        return 0

    summaries = []
    for p in json_files:
        s = _load_result_summary(p)
        if s:
            summaries.append(s)

    if sort_by == "score":
        summaries.sort(key=lambda s: s["global_score"], reverse=True)
    elif sort_by == "asset":
        summaries.sort(key=lambda s: s["assets"])
    else:  # time
        summaries.sort(key=lambda s: s["timestamp"], reverse=True)

    print(f"{'File':<45} {'Assets':<20} {'Score':>7} {'#Assets':>7} {'Time':>7}")
    print("-" * 90)

    for s in summaries:
        time_min = s["total_time_seconds"] / 60
        print(
            f"{s['file']:<45} {s['assets']:<20} "
            f"{s['global_score']:>7.4f} {s['n_asset_results']:>7d} "
            f"{time_min:>6.1f}m"
        )

    print(f"\n{len(summaries)} result(s) in {_RESULTS_DIR}")
    return 0


# ---------------------------------------------------------------------------
# watch
# ---------------------------------------------------------------------------

def cmd_watch(status_file: str, interval: int = 5) -> int:
    """Watch live optimization progress via the status file."""
    print()
    print("  ======================================")
    print("    S/R Optimization Monitor")
    print("  ======================================")
    print(f"  Watching: {status_file}")
    print(f"  Polling every {interval}s  (Ctrl+C to stop)")
    print()

    last_status: dict | None = None

    try:
        while True:
            try:
                with open(status_file) as f:
                    s = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                print(f"\r  Waiting for status file ...", end="", flush=True)
                time.sleep(interval)
                continue

            # Detect stale file from a previous run
            pid = s.get("pid")
            if last_status is None and not _check_process_alive(pid):
                st = s.get("status", "?")
                print(f"  Stale status file (PID {pid}, status={st}). Waiting...\n")
                time.sleep(interval)
                continue

            status = s.get("status", "unknown").upper()
            stage = s.get("stage", "?")
            assets = s.get("assets", [])

            # Stage 1 progress
            s1_cur = s.get("stage1_trial_current", 0)
            s1_total = s.get("stage1_n_trials_target", 0)
            s1_best = s.get("stage1_best_score", 0.0)

            # Stage 2 progress
            s2_asset = s.get("stage2_asset_current")
            s2_tf = s.get("stage2_tf_current")
            s2_completed = s.get("stage2_assets_completed", 0)
            s2_total = s.get("stage2_assets_total", 0)
            s2_trial_cur = s.get("stage2_trial_current", 0)
            s2_trial_target = s.get("stage2_n_trials_target", 0)

            # Fallback: read per_asset_n_trials from YAML config if
            # the status file was written by an older status_writer that
            # didn't include stage2_n_trials_target.
            if s2_trial_target == 0:
                s2_trial_target = _load_s2_trials_from_config()

            # Stage 1 progress bar
            s1_pct = (s1_cur / s1_total * 100) if s1_total > 0 else 0.0
            bar_len = 30
            filled = int(bar_len * s1_pct / 100)
            bar = "=" * filled + "-" * (bar_len - filled)

            # Elapsed + ETA
            start_str = s.get("start_time", "")
            elapsed_str = "?"
            eta_str = "calculating..."
            if start_str:
                try:
                    start_dt = datetime.fromisoformat(start_str)
                    now = datetime.now(UTC) if start_dt.tzinfo else datetime.now()
                    elapsed = (now - start_dt).total_seconds()
                    elapsed_str = _format_duration(elapsed)
                    if stage == "stage1" and s1_cur >= 3:
                        rate = s1_cur / max(elapsed, 1.0)
                        remaining = (s1_total - s1_cur) / max(rate, 0.001)
                        eta_str = f"~{_format_duration(remaining)}"
                    elif stage == "stage2" and s2_trial_target > 0 and s2_trial_cur >= 2:
                        # Use trial-level progress for granular ETA
                        done_units = s2_completed * s2_trial_target + s2_trial_cur
                        total_units = s2_total * s2_trial_target
                        # Use stage2_start_time if available for more accurate rate
                        s2_start_str = s.get("stage2_start_time", "")
                        s2_elapsed = 0.0
                        if s2_start_str:
                            s2_start_dt = datetime.fromisoformat(s2_start_str)
                            s2_elapsed = (now - s2_start_dt).total_seconds()
                        else:
                            # Fallback: estimate Stage 2 elapsed from Stage 1
                            # rate — Stage 1 consumed (s1_total / rate) seconds
                            if s1_total > 0 and s1_cur > 0:
                                s1_rate = elapsed / s1_cur if s1_cur < s1_total else 0.0
                                s1_estimated = s1_total * s1_rate if s1_rate > 0 else elapsed * 0.3
                                s2_elapsed = max(elapsed - s1_estimated, elapsed * 0.5)
                            else:
                                s2_elapsed = elapsed * 0.7
                        if done_units >= 2 and s2_elapsed > 0:
                            rate = done_units / max(s2_elapsed, 1.0)
                            remaining = (total_units - done_units) / max(rate, 0.001)
                            eta_str = f"~{_format_duration(remaining)}"
                except Exception:
                    pass

            alive = _check_process_alive(pid) if isinstance(pid, int) else None
            alive_str = "alive" if alive else ("DEAD" if alive is False else "?")

            # Build output
            output = (
                f"\n  Assets:    {', '.join(assets)}\n"
                f"  Status:    {status} ({stage})\n"
                f"\n"
                f"  Stage 1:   [{bar}] {s1_cur}/{s1_total} ({s1_pct:.1f}%)\n"
                f"  S1 Best:   {s1_best:.4f}\n"
            )

            if stage == "stage2" or s2_completed > 0:
                s2_pct = (s2_completed / s2_total * 100) if s2_total > 0 else 0.0
                current_str = f"{s2_asset}/{s2_tf}" if s2_asset else "—"
                output += (
                    f"\n"
                    f"  Stage 2:   {s2_completed}/{s2_total} ({s2_pct:.1f}%)\n"
                    f"  Current:   {current_str}\n"
                )
                # Show per-asset trial progress bar
                if s2_trial_target > 0 and s2_asset:
                    t_pct = (s2_trial_cur / s2_trial_target * 100) if s2_trial_target > 0 else 0.0
                    t_filled = int(bar_len * t_pct / 100)
                    t_bar = "=" * t_filled + "-" * (bar_len - t_filled)
                    output += f"  Trials:    [{t_bar}] {s2_trial_cur}/{s2_trial_target} ({t_pct:.1f}%)\n"

            output += (
                f"\n"
                f"  ETA:       {eta_str}\n"
                f"  Elapsed:   {elapsed_str}\n"
                f"  Process:   PID {pid} ({alive_str})\n"
                f"  {'='*38}\n"
            )

            n_lines = output.count("\n")
            if last_status is not None:
                sys.stdout.write(f"\033[{n_lines}A")
            sys.stdout.write(output)
            sys.stdout.flush()

            # Terminal states
            if s.get("status") == "completed":
                print(f"\n  COMPLETED — Global score: {s1_best:.4f}")
                return 0
            if s.get("status") == "failed":
                print(f"\n  FAILED — {s.get('error', 'unknown error')}")
                return 1

            if isinstance(pid, int) and not _check_process_alive(pid):
                print(f"\n  WARNING: PID {pid} no longer running. Optimizer may have crashed.")
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
        d1 = _load_result_json(path1)
        d2 = _load_result_json(path2)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: Failed to load results: {exc}", file=sys.stderr)
        return 1

    name1 = Path(path1).name
    name2 = Path(path2).name

    print("=" * 75)
    print("  S/R OPTIMIZATION COMPARISON")
    print("=" * 75)
    print(f"  {'':30s} {'Run A':>20s} {'Run B':>20s}")
    print(f"  {'File':30s} {name1:>20s} {name2:>20s}")
    print()

    # Global scores
    print("  GLOBAL SCORES")
    _compare_row("Global Score", d1.get("global_score", 0.0), d2.get("global_score", 0.0))

    m1 = d1.get("metadata", {})
    m2 = d2.get("metadata", {})
    _compare_row("Stage 1 Trials", m1.get("stage1_n_trials", 0), m2.get("stage1_n_trials", 0), fmt="d")
    _compare_row("S2 Accepted", m1.get("stage2_assets_accepted", 0), m2.get("stage2_assets_accepted", 0), fmt="d")
    _compare_row("Time (s)", m1.get("total_time_seconds", 0), m2.get("total_time_seconds", 0), fmt=".0f")
    print()

    # Per-asset comparison
    r1_map = {(r["asset"], r["timeframe"]): r for r in d1.get("per_asset_results", [])}
    r2_map = {(r["asset"], r["timeframe"]): r for r in d2.get("per_asset_results", [])}
    all_keys = sorted(set(r1_map) | set(r2_map))

    if all_keys:
        print("  PER-ASSET SCORES")
        for key in all_keys:
            asset, tf = key
            label = f"{asset}/{tf}"
            v1 = r1_map.get(key, {}).get("val_score", 0.0)
            v2 = r2_map.get(key, {}).get("val_score", 0.0)
            _compare_row(label, v1, v2)
        print()

    # Global params diff
    p1 = d1.get("global_params", {})
    p2 = d2.get("global_params", {})
    all_param_keys = sorted(set(p1) | set(p2))
    if all_param_keys:
        print("  GLOBAL PARAMETER DIFF")
        for key in all_param_keys:
            v1 = p1.get(key)
            v2 = p2.get(key)
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


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
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
