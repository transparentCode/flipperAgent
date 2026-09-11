"""Tests for SR scripts shared utilities and status writer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.sr.scripts._utils import _ensure_utc, _parse_date, get_optimal_lookback_days
from app.sr.scripts.status_writer import SRStatusFileWriter


# -----------------------------------------------------------------------
# _ensure_utc
# -----------------------------------------------------------------------

class TestEnsureUtc:
    def test_naive_to_utc(self):
        """Naive DatetimeIndex should be localized to UTC."""
        idx = pd.date_range("2025-01-01", periods=5, freq="1h")
        df = pd.DataFrame({"close": np.arange(5, dtype=float)}, index=idx)
        assert df.index.tz is None

        result = _ensure_utc(df)
        assert result.index.tz is not None
        assert str(result.index.tz) == "UTC"
        # Original unchanged
        assert df.index.tz is None

    def test_convert_to_utc(self):
        """Tz-aware index in another timezone should be converted to UTC."""
        idx = pd.date_range("2025-01-01", periods=5, freq="1h", tz="US/Eastern")
        df = pd.DataFrame({"close": np.arange(5, dtype=float)}, index=idx)
        assert str(df.index.tz) != "UTC"

        result = _ensure_utc(df)
        assert str(result.index.tz) == "UTC"

    def test_already_utc(self):
        """UTC index should pass through without error."""
        idx = pd.date_range("2025-01-01", periods=5, freq="1h", tz="UTC")
        df = pd.DataFrame({"close": np.arange(5, dtype=float)}, index=idx)

        result = _ensure_utc(df)
        assert str(result.index.tz) == "UTC"
        assert len(result) == 5


# -----------------------------------------------------------------------
# _parse_date
# -----------------------------------------------------------------------

class TestParseDate:
    def test_valid(self):
        dt = _parse_date("2025-06-15")
        assert dt.year == 2025
        assert dt.month == 6
        assert dt.day == 15

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_date("not-a-date")


class TestGetOptimalLookbackDays:
    @pytest.mark.parametrize(
        ("timeframe", "expected"),
        [
            ("1m", 30),
            ("15m", 60),
            ("1h", 90),
            ("4h", 180),
            ("1d", 365),
            ("1w", 1825),
        ],
    )
    def test_known_timeframes(self, timeframe: str, expected: int):
        assert get_optimal_lookback_days(timeframe) == expected

    def test_unknown_timeframe_falls_back_to_90_days(self):
        assert get_optimal_lookback_days("custom") == 90


# -----------------------------------------------------------------------
# SRStatusFileWriter
# -----------------------------------------------------------------------

class TestSRStatusFileWriter:
    def test_lifecycle(self, tmp_path: Path):
        """Full lifecycle: init → stage1 update → stage2 start → complete."""
        writer = SRStatusFileWriter(
            output_dir=tmp_path,
            assets=["BTCUSDT", "ETHUSDT"],
            timeframes=["1h"],
            n_trials=50,
            per_asset_n_trials=20,
        )
        status_file = tmp_path / ".optimization_status.json"
        assert status_file.exists()

        # Initial state
        data = json.loads(status_file.read_text())
        assert data["status"] == "starting"
        assert data["stage"] == "stage1"
        assert data["assets"] == ["BTCUSDT", "ETHUSDT"]
        assert data["timeframes"] == ["1h"]
        assert data["stage2_assets_total"] == 2
        assert data["stage2_n_trials_target"] == 20
        assert data["stage2_trial_current"] == 0

        # Stage 1 update
        writer.update_stage1(trial_current=10, best_score=0.75, best_params={"a": 1})
        data = json.loads(status_file.read_text())
        assert data["status"] == "running"
        assert data["stage"] == "stage1"
        assert data["stage1_trial_current"] == 10
        assert data["stage1_best_score"] == 0.75
        assert data["stage1_best_params"] == {"a": 1}

        # Stage 2 start
        writer.start_stage2("BTCUSDT", "1h")
        data = json.loads(status_file.read_text())
        assert data["stage"] == "stage2"
        assert data["stage2_asset_current"] == "BTCUSDT"
        assert data["stage2_tf_current"] == "1h"
        assert data["stage2_trial_current"] == 0
        assert data["stage2_n_trials_target"] == 20
        assert "stage2_start_time" in data

        # Stage 2 update
        writer.update_stage2("BTCUSDT", "1h", trial_current=5, best_score=0.80)
        data = json.loads(status_file.read_text())
        assert data["stage2_trial_current"] == 5
        assert data["stage2_best_score"] == 0.80
        assert data["stage2_n_trials_target"] == 20

        # Stage 2 complete for first asset
        writer.complete_stage2("BTCUSDT", "1h")
        data = json.loads(status_file.read_text())
        assert data["stage2_assets_completed"] == 1

        # Stage 2 complete for second asset
        writer.start_stage2("ETHUSDT", "1h")
        writer.complete_stage2("ETHUSDT", "1h")
        data = json.loads(status_file.read_text())
        assert data["stage2_assets_completed"] == 2

        # Full completion
        writer.complete()
        data = json.loads(status_file.read_text())
        assert data["status"] == "completed"
        assert data["stage"] == "done"

    def test_atomic_write(self, tmp_path: Path):
        """Status file should exist after each write — no partial states."""
        writer = SRStatusFileWriter(
            output_dir=tmp_path,
            assets=["BTCUSDT"],
            timeframes=["1h"],
            n_trials=10,
        )
        status_file = tmp_path / ".optimization_status.json"

        # Write multiple updates and verify file is always valid JSON
        for i in range(5):
            writer.update_stage1(trial_current=i, best_score=float(i) / 10)
            data = json.loads(status_file.read_text())
            assert data["stage1_trial_current"] == i

    def test_fail_state(self, tmp_path: Path):
        """fail() should write error message and failed status."""
        writer = SRStatusFileWriter(
            output_dir=tmp_path,
            assets=["BTCUSDT"],
            timeframes=["1h"],
            n_trials=10,
        )
        writer.fail("Optuna not installed")

        data = json.loads((tmp_path / ".optimization_status.json").read_text())
        assert data["status"] == "failed"
        assert data["error"] == "Optuna not installed"

    def test_pid_recorded(self, tmp_path: Path):
        """Status file should contain current process PID."""
        import os
        writer = SRStatusFileWriter(
            output_dir=tmp_path,
            assets=["BTCUSDT"],
            timeframes=["1h"],
            n_trials=10,
        )
        data = json.loads((tmp_path / ".optimization_status.json").read_text())
        assert data["pid"] == os.getpid()

    def test_stale_removal(self, tmp_path: Path):
        """Init should remove a stale status file from a previous run."""
        stale = tmp_path / ".optimization_status.json"
        stale.write_text('{"status": "running", "pid": 99999}')

        writer = SRStatusFileWriter(
            output_dir=tmp_path,
            assets=["BTCUSDT"],
            timeframes=["1h"],
            n_trials=10,
        )
        data = json.loads(stale.read_text())
        assert data["status"] == "starting"  # Not stale "running"

    def test_creates_output_dir(self, tmp_path: Path):
        """Should create output_dir if it doesn't exist."""
        nested = tmp_path / "deep" / "nested" / "dir"
        assert not nested.exists()

        writer = SRStatusFileWriter(
            output_dir=nested,
            assets=["BTCUSDT"],
            timeframes=["1h"],
            n_trials=10,
        )
        assert nested.exists()
        assert (nested / ".optimization_status.json").exists()
