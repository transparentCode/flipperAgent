"""
Trendlines Optimization Monitor.

Polls the status file written by run_optimization.py and displays
real-time progress including trial count, best score, stage info,
and ETA.

Usage
-----
python app/trendlines/scripts/monitor_optimization.py

# Custom status file path
python app/trendlines/scripts/monitor_optimization.py \
    --status-file app/trendlines/optimization/results/.optimization_status.json

# Faster polling
python app/trendlines/scripts/monitor_optimization.py --interval 1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path


class OptimizationMonitor:
    """Real-time monitor for trendlines optimization status."""

    def __init__(self, status_file: str, poll_interval: float = 3.0):
        self.status_path = Path(status_file)
        self.poll_interval = poll_interval
        self._last_data: dict = {}
        self._start_time: float | None = None
        self._last_trial: int = 0

    def run(self) -> None:
        print(f"Monitoring: {self.status_path.resolve()}")
        print("Waiting for optimization to start...\n")

        try:
            while True:
                data = self._read_status()
                if data:
                    self._display(data)
                    if data.get("status") in ("completed", "failed"):
                        break
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            print("\nMonitor stopped.")

    def _read_status(self) -> dict | None:
        if not self.status_path.exists():
            return None
        try:
            with open(self.status_path) as f:
                data = json.load(f)
            return data
        except (json.JSONDecodeError, OSError):
            return None

    def _check_pid(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def _display(self, data: dict) -> None:
        status = data.get("status", "unknown")
        trial_current = data.get("trial_current", 0)
        trial_total = data.get("trial_total", 0)
        best_score = data.get("best_score", 0.0)
        stage = data.get("stage", "")
        stage_name = data.get("stage_name", "")
        asset = data.get("asset", "?")
        timeframe = data.get("timeframe", "?")
        pid = data.get("pid")
        start_time_str = data.get("start_time")
        last_update = data.get("last_update", "")

        # Track timing for ETA
        if self._start_time is None and start_time_str:
            try:
                self._start_time = datetime.fromisoformat(start_time_str).timestamp()
            except ValueError:
                pass

        # ETA calculation
        eta_str = "—"
        if self._start_time and trial_current > 0 and trial_total > 0:
            elapsed = time.time() - self._start_time
            rate = trial_current / elapsed
            remaining = (trial_total - trial_current) / rate if rate > 0 else 0
            eta_str = str(timedelta(seconds=int(remaining)))

        # Elapsed
        elapsed_str = "—"
        if self._start_time:
            elapsed_str = str(timedelta(seconds=int(time.time() - self._start_time)))

        # Progress bar
        pct = trial_current / trial_total * 100 if trial_total > 0 else 0
        bar_width = 30
        filled = int(bar_width * pct / 100)
        bar = "█" * filled + "░" * (bar_width - filled)

        # PID health
        pid_status = ""
        if pid:
            alive = self._check_pid(pid)
            pid_status = f"PID {pid} ({'alive' if alive else 'DEAD'})"
            if not alive and status == "running":
                status = "ZOMBIE (process dead)"

        # Clear and redraw
        sys.stdout.write("\033[2J\033[H")  # clear + home
        sys.stdout.write(
            f"  Trendlines Optimization Monitor\n"
            f"  ================================\n\n"
            f"  Asset:     {asset} {timeframe}\n"
            f"  Status:    {status.upper()}\n"
            f"  Stage:     {stage_name} ({stage})\n"
            f"  Process:   {pid_status}\n"
            f"\n"
            f"  Progress:  [{bar}] {pct:5.1f}%\n"
            f"  Trials:    {trial_current} / {trial_total}\n"
            f"  Best:      {best_score:.6f}\n"
            f"\n"
            f"  Elapsed:   {elapsed_str}\n"
            f"  ETA:       {eta_str}\n"
            f"  Updated:   {last_update}\n"
        )

        # Show final metrics if completed
        if status == "completed":
            metrics = data.get("metrics_summary", {})
            if metrics:
                sys.stdout.write(
                    f"\n"
                    f"  Final Metrics\n"
                    f"  {'—' * 30}\n"
                )
                for k, v in sorted(metrics.items()):
                    if isinstance(v, float):
                        sys.stdout.write(f"  {k:30s} {v:.4f}\n")
                    else:
                        sys.stdout.write(f"  {k:30s} {v}\n")

            sys.stdout.write(f"\n  Optimization complete.\n")

        elif status == "failed":
            errors = data.get("errors", [])
            sys.stdout.write(f"\n  ERRORS:\n")
            for e in errors:
                sys.stdout.write(f"    - {e}\n")

        sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(
        description="Monitor trendlines optimization progress",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--status-file", type=str,
        default="app/trendlines/optimization/results/.optimization_status.json",
        help="Path to the status JSON file",
    )
    parser.add_argument(
        "--interval", type=float, default=3.0,
        help="Poll interval in seconds",
    )
    args = parser.parse_args()

    # Resolve relative paths from project root
    status_file = args.status_file
    if not Path(status_file).is_absolute():
        root = Path(__file__).resolve().parents[3]
        status_file = str(root / status_file)

    monitor = OptimizationMonitor(status_file, args.interval)
    monitor.run()


if __name__ == "__main__":
    main()
