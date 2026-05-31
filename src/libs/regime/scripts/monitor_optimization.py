"""
Regime Optimization Monitor.

Watches the status file written by run_optimization.py and displays
real-time progress, ETA, and process health.

Cross-platform: works on macOS, Linux, Windows, and Docker.
psutil is optional (graceful degradation without it).

Usage
-----
# In a separate terminal while run_optimization.py is running:
python app/regime/scripts/monitor_optimization.py \
    --status-file app/regime/optimization/results/.optimization_status.json

# With custom poll interval and timeout:
python app/regime/scripts/monitor_optimization.py \
    --status-file app/regime/optimization/results/.optimization_status.json \
    --interval 5 --timeout 7200

# Machine-readable JSON output:
python app/regime/scripts/monitor_optimization.py \
    --status-file app/regime/optimization/results/.optimization_status.json \
    --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


class OptimizationMonitor:
    """Polls a JSON status file and displays optimization progress."""

    def __init__(
        self,
        status_path: Path,
        poll_interval: float = 10.0,
        timeout: Optional[float] = None,
        json_mode: bool = False,
    ):
        self.status_path = status_path.resolve()
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.json_mode = json_mode
        self._start_time = time.time()
        self._last_status: Optional[dict] = None
        self._stale_count = 0

    def run(self) -> int:
        """
        Main polling loop.

        Returns
        -------
        0  optimization completed successfully
        1  optimization failed
        2  monitor timed out
        3  optimizer process died (status file stale + PID dead)
        """
        print(self._banner())

        while True:
            status = self._read_status()

            if status is None:
                self._print_waiting()
            else:
                # Detect stale status file from a previous run:
                # if this is the first read and status is terminal and PID is dead,
                # the file is leftover — inform the user but don't delete it
                # (the optimizer cleans up stale files on startup).
                if self._last_status is None and self._is_stale(status):
                    self._print_stale(status)
                    # Wait for the new optimizer to overwrite the file
                    time.sleep(self.poll_interval)
                    continue

                if self.json_mode:
                    print(json.dumps(status, indent=2))
                else:
                    self._print_status(status)

                # Check terminal states
                if status.get("status") == "completed":
                    self._print_completed(status)
                    return 0
                if status.get("status") == "failed":
                    self._print_failed(status)
                    return 1

                # Check if optimizer process is still alive
                pid = status.get("pid")
                if pid and not self._check_process_alive(pid):
                    self._stale_count += 1
                    if self._stale_count >= 3:
                        print(f"\n  WARNING: Process PID {pid} is no longer running.")
                        print("  The optimization may have crashed without updating status.")
                        return 3
                else:
                    self._stale_count = 0

                self._last_status = status

            # Check timeout
            if self._timed_out():
                print(f"\n  Monitor timed out after {self.timeout:.0f}s")
                return 2

            time.sleep(self.poll_interval)

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def _banner(self) -> str:
        return (
            "\n"
            "  ======================================\n"
            "    Regime Optimization Monitor\n"
            "  ======================================\n"
            f"  Watching: {self.status_path}\n"
        )

    def _print_waiting(self) -> None:
        elapsed = time.time() - self._start_time
        print(f"\r  Waiting for status file at {self.status_path} ... ({elapsed:.0f}s elapsed)", end="", flush=True)

    def _print_status(self, s: dict) -> None:
        asset = s.get("asset", "?")
        tf = s.get("timeframe", "?")
        stage = s.get("stage", "?")
        stage_name = s.get("stage_name", "")
        status = s.get("status", "unknown").upper()
        trial_cur = s.get("trial_current", 0)
        trial_total = s.get("trial_total", 0)
        best = s.get("best_score", 0.0)
        pid = s.get("pid", "?")
        last_update = s.get("last_update", "")

        # Progress
        pct = (trial_cur / trial_total * 100) if trial_total > 0 else 0.0
        bar_len = 30
        filled = int(bar_len * pct / 100)
        bar = "=" * filled + "-" * (bar_len - filled)

        # ETA
        eta_str = self._format_eta(s)

        # Elapsed
        start_str = s.get("start_time", "")
        if start_str:
            try:
                start_dt = datetime.fromisoformat(start_str)
                elapsed = (datetime.now() - start_dt).total_seconds()
                elapsed_str = self._format_duration(elapsed)
            except Exception:
                elapsed_str = "?"
        else:
            elapsed_str = "?"

        # Process alive check
        alive = self._check_process_alive(pid) if isinstance(pid, int) else None
        alive_str = "alive" if alive else ("DEAD" if alive is False else "?")

        # Format update time
        if last_update:
            try:
                update_dt = datetime.fromisoformat(last_update)
                update_str = update_dt.strftime("%H:%M:%S")
            except Exception:
                update_str = last_update
        else:
            update_str = "?"

        # Clear and print
        output = (
            f"\r\033[K"  # clear line
            f"\n  Asset:     {asset} {tf}\n"
            f"  Stage:     {stage} ({stage_name})\n"
            f"  Status:    {status}\n"
            f"\n"
            f"  Progress:  [{bar}] {trial_cur}/{trial_total} ({pct:.1f}%)\n"
            f"  Best:      {best:.4f}\n"
            f"  ETA:       {eta_str}\n"
            f"  Elapsed:   {elapsed_str}\n"
            f"\n"
            f"  Process:   PID {pid} ({alive_str})\n"
            f"  Updated:   {update_str}\n"
            f"  {'='*38}\n"
        )

        # Move cursor up to overwrite previous output (13 lines)
        if self._last_status is not None:
            sys.stdout.write(f"\033[13A")
        sys.stdout.write(output)
        sys.stdout.flush()

    def _print_completed(self, s: dict) -> None:
        print(f"\n  COMPLETED -- Best score: {s.get('best_score', 0):.4f}")
        best_params = s.get("best_params", {})
        if best_params:
            print("  Best params:")
            for k, v in best_params.items():
                print(f"    {k:30s} = {v}")
        metrics = s.get("metrics_summary", {})
        if metrics:
            print("  Key metrics:")
            for k in ["sharpe_improvement", "forward_return_ic", "cp_precision"]:
                if k in metrics:
                    print(f"    {k:30s} = {metrics[k]:.4f}")

    def _print_failed(self, s: dict) -> None:
        errors = s.get("errors", [])
        print(f"\n  FAILED")
        for err in errors:
            print(f"    Error: {err}")

    def _print_stale(self, s: dict) -> None:
        pid = s.get("pid", "?")
        status = s.get("status", "?")
        start = s.get("start_time", "?")
        print(
            f"\n  Stale status file from previous run (PID {pid}, status={status}, started={start}).\n"
            f"  Waiting for new optimizer to overwrite it...\n"
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _is_stale(self, status: dict) -> bool:
        """Check if status file is stale from a previous run.

        A status is stale when the PID that wrote it is no longer running —
        covers both terminal states (completed/failed) and crashed optimizers
        that left a "running" status behind.
        """
        pid = status.get("pid")
        if not isinstance(pid, int):
            return False
        return not self._check_process_alive(pid)

    def _read_status(self) -> Optional[dict]:
        """Safely read status JSON. Returns None if missing or invalid."""
        try:
            with open(self.status_path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def _check_process_alive(self, pid) -> bool:
        """Check if the optimizer PID is still running. Cross-platform."""
        if not isinstance(pid, int):
            return True  # can't check, assume alive

        # Try psutil first (most reliable, cross-platform)
        try:
            import psutil
            return psutil.pid_exists(pid)
        except ImportError:
            pass

        # Fallback: os.kill signal 0 (works on macOS/Linux)
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # process exists but we lack permission
        except OSError:
            return False
        except Exception:
            return True  # unknown error, assume alive

    def _format_eta(self, s: dict) -> str:
        """Estimate time remaining from trial progress and elapsed time."""
        trial_cur = s.get("trial_current", 0)
        trial_total = s.get("trial_total", 0)

        if trial_cur < 3 or trial_total <= 0:
            return "calculating..."

        start_str = s.get("start_time", "")
        if not start_str:
            return "?"

        try:
            start_dt = datetime.fromisoformat(start_str)
            elapsed = (datetime.now() - start_dt).total_seconds()
        except Exception:
            return "?"

        rate = trial_cur / max(elapsed, 1.0)
        remaining = (trial_total - trial_cur) / max(rate, 0.001)
        return self._format_duration(remaining)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format seconds into human-readable string."""
        if seconds < 0:
            return "?"
        hours, remainder = divmod(int(seconds), 3600)
        minutes, secs = divmod(remainder, 60)
        if hours > 0:
            return f"~{hours}h {minutes:02d}m"
        return f"~{minutes}m {secs:02d}s"

    def _timed_out(self) -> bool:
        if self.timeout is None:
            return False
        return (time.time() - self._start_time) > self.timeout


def _project_root() -> Path:
    """Resolve project root from script location (3 levels up from scripts/)."""
    return Path(__file__).resolve().parents[3]


def _default_status_path() -> str:
    """Absolute default path to the status file."""
    return str(
        _project_root() / "app" / "regime" / "optimization" / "results"
        / ".optimization_status.json"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Monitor regime optimization progress",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--status-file",
        type=str,
        default=_default_status_path(),
        help="Path to .optimization_status.json",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=10.0,
        help="Poll interval in seconds",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Max wait time in seconds (None = wait forever)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted display",
    )

    args = parser.parse_args()
    status_path = Path(args.status_file)

    monitor = OptimizationMonitor(
        status_path=status_path,
        poll_interval=args.interval,
        timeout=args.timeout,
        json_mode=args.json,
    )

    try:
        exit_code = monitor.run()
    except KeyboardInterrupt:
        print("\n\n  Monitor stopped by user.")
        exit_code = 0

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
