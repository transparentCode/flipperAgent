"""Tests for TradingView backfill quality manifests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

_SPEC = importlib.util.spec_from_file_location(
    "tv_data_quality",
    Path(__file__).resolve().parents[1] / "scripts" / "tv_data_quality.py",
)
tv_data_quality = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
sys.modules[_SPEC.name] = tv_data_quality
_SPEC.loader.exec_module(tv_data_quality)


def _write_csv(path: Path, timestamps: list[int]) -> None:
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "value": [float(idx) for idx in range(len(timestamps))],
        }
    )
    frame["datetime"] = pd.to_datetime(frame["timestamp"], unit="s", utc=True)
    frame.to_csv(path, index=False)


def test_evaluate_file_accepts_clean_history(tmp_path):
    path = tmp_path / "CRYPTOCAP_TOTAL2_4h_ohlcv.csv"
    start = 1_735_689_600
    _write_csv(path, [start + idx * 14_400 for idx in range(10)])

    report = tv_data_quality.evaluate_file(path, min_days=1.0)

    assert report.status == "ok"
    assert report.rows == 10
    assert report.gap_count == 0


def test_evaluate_file_rejects_insufficient_history(tmp_path):
    path = tmp_path / "CRYPTOCAP_TOTAL2_1h_ohlcv.csv"
    start = 1_775_001_600
    _write_csv(path, [start + idx * 3_600 for idx in range(24)])

    report = tv_data_quality.evaluate_file(path, min_days=30.0)

    assert report.status == "reject"
    assert "insufficient_history" in report.reasons


def test_evaluate_file_rejects_large_gaps(tmp_path):
    path = tmp_path / "CRYPTOCAP_TOTAL2_1h_ohlcv.csv"
    _write_csv(path, [1_000, 4_600, 30_000])

    report = tv_data_quality.evaluate_file(path, min_days=0.0)

    assert report.status == "reject"
    assert "large_gaps" in report.reasons


def test_funding_files_are_sparse_allowed_with_eight_hour_interval(tmp_path):
    path = tmp_path / "BINANCE_BNBUSDT.P_FR_1h_series.csv"
    start = 1_735_689_600
    _write_csv(path, [start + idx * 28_800 for idx in range(5)])

    report = tv_data_quality.evaluate_file(path, min_days=1.0)

    assert report.status == "ok"
    assert report.expected_interval_seconds == 28_800
    assert report.sparse_allowed is True


def test_build_manifest_lists_accepted_and_rejected(tmp_path):
    good_path = tmp_path / "good_TOTAL2_1h_ohlcv.csv"
    bad_path = tmp_path / "bad_TOTAL2_1h_ohlcv.csv"
    start = 1_775_001_600
    _write_csv(good_path, [start + idx * 3_600 for idx in range(48)])
    _write_csv(bad_path, [start, start + 100_000])

    reports = [
        tv_data_quality.evaluate_file(good_path, min_days=1.0),
        tv_data_quality.evaluate_file(bad_path, min_days=1.0),
    ]
    manifest = tv_data_quality.build_manifest(reports)

    assert manifest["summary"] == {"total": 2, "accepted": 1, "rejected": 1}
    assert str(good_path) in manifest["accepted_paths"]
    assert str(bad_path) in manifest["rejected_paths"]
