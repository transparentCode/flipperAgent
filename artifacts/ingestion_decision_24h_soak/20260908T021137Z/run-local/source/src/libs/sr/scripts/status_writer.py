"""Two-stage-aware optimization status file writer.

Writes an atomic JSON status file that a monitor process can poll to
track Stage 1 (global) and Stage 2 (per-asset) optimization progress.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional


_STATUS_FILENAME = ".optimization_status.json"


class SRStatusFileWriter:
    """Atomic JSON status writer for SR two-stage optimization.

    The status file is written to ``output_dir / .optimization_status.json``
    and is overwritten on every update via tempfile + ``os.replace()``
    for crash safety.

    Parameters
    ----------
    output_dir : Path
        Directory where the status file is created (typically
        ``app/sr/optimization/results/``).
    assets : list[str]
        Assets being optimized.
    timeframes : list[str]
        Timeframes being optimized.
    n_trials : int
        Target trial count for Stage 1.
    """

    def __init__(
        self,
        output_dir: Path,
        assets: list[str],
        timeframes: list[str],
        n_trials: int,
        per_asset_n_trials: int = 30,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.status_path = self.output_dir / _STATUS_FILENAME
        self._n_trials = n_trials
        self._per_asset_n_trials = per_asset_n_trials
        self._base: dict[str, Any] = {
            "pid": os.getpid(),
            "assets": assets,
            "timeframes": timeframes,
            "start_time": datetime.now(UTC).isoformat(),
        }
        self._stage2_total = len(assets) * len(timeframes)
        self._stage2_started = False

        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Remove stale status file from previous runs
        if self.status_path.exists():
            self.status_path.unlink()

        self._write(
            status="starting",
            stage="stage1",
            stage1_trial_current=0,
            stage1_n_trials_target=n_trials,
            stage1_best_score=0.0,
            stage1_best_params={},
            stage2_asset_current=None,
            stage2_tf_current=None,
            stage2_assets_completed=0,
            stage2_assets_total=self._stage2_total,
            stage2_n_trials_target=per_asset_n_trials,
            stage2_trial_current=0,
        )

    # ------------------------------------------------------------------
    # Stage 1 updates
    # ------------------------------------------------------------------

    def update_stage1(
        self,
        trial_current: int,
        best_score: float,
        best_params: Optional[dict] = None,
    ) -> None:
        """Update Stage 1 progress (called per-trial)."""
        self._write(
            status="running",
            stage="stage1",
            stage1_trial_current=trial_current,
            stage1_n_trials_target=self._n_trials,
            stage1_best_score=best_score,
            stage1_best_params=best_params or {},
            stage2_asset_current=None,
            stage2_tf_current=None,
            stage2_assets_completed=0,
            stage2_assets_total=self._stage2_total,
        )

    # ------------------------------------------------------------------
    # Stage 2 updates
    # ------------------------------------------------------------------

    def start_stage2(self, asset: str, timeframe: str) -> None:
        """Signal that Stage 2 optimization is starting for an asset/tf pair."""
        extra: dict[str, Any] = {}
        if not self._stage2_started:
            extra["stage2_start_time"] = datetime.now(UTC).isoformat()
            self._stage2_started = True
        self._write(
            status="running",
            stage="stage2",
            stage2_asset_current=asset,
            stage2_tf_current=timeframe,
            stage2_trial_current=0,
            stage2_n_trials_target=self._per_asset_n_trials,
            **extra,
        )

    def update_stage2(
        self,
        asset: str,
        timeframe: str,
        trial_current: int,
        best_score: float,
    ) -> None:
        """Update Stage 2 per-trial progress for a specific asset/tf."""
        self._write(
            status="running",
            stage="stage2",
            stage2_asset_current=asset,
            stage2_tf_current=timeframe,
            stage2_trial_current=trial_current,
            stage2_best_score=best_score,
            stage2_n_trials_target=self._per_asset_n_trials,
        )

    def complete_stage2(self, asset: str, timeframe: str) -> None:
        """Signal that Stage 2 is done for one asset/tf pair.

        Note: read-modify-write is not atomic; assumes single-writer
        (one optimizer process at a time).
        """
        # Read current completed count from last status
        current = self._read_current()
        completed = current.get("stage2_assets_completed", 0) + 1
        self._write(
            status="running",
            stage="stage2",
            stage2_asset_current=None,
            stage2_tf_current=None,
            stage2_assets_completed=completed,
            stage2_assets_total=self._stage2_total,
        )

    # ------------------------------------------------------------------
    # Terminal states
    # ------------------------------------------------------------------

    def complete(self, result: Any = None) -> None:
        """Signal successful completion of the full two-stage optimization."""
        self._write(
            status="completed",
            stage="done",
            stage2_assets_completed=self._stage2_total,
            stage2_assets_total=self._stage2_total,
        )

    def fail(self, error_msg: str) -> None:
        """Signal optimization failure."""
        self._write(
            status="failed",
            error=error_msg,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _read_current(self) -> dict:
        """Read current status file for incremental updates."""
        try:
            with open(self.status_path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _write(self, **fields: Any) -> None:
        """Merge *fields* into the current status and write atomically."""
        current = self._read_current()
        data = {**self._base, **current, "last_update": datetime.now(UTC).isoformat(), **fields}
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=self.output_dir, suffix=".tmp",
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
