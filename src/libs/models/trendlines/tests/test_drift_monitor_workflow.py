"""Tests for the trendlines-owned drift monitor workflow."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd

from libs.models.trendlines.boundary import BoundaryResult, QualityMetrics, Ray
from libs.models.trendlines.workflows.monitoring.drift_monitor import build_monitor_snapshot, compare, run_monitor


def _make_ray(*, is_support: bool, score: float, r_squared: float, metadata: dict) -> Ray:
    return Ray(
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-01-02"),
        95.0,
        96.0,
        0.5,
        94.5,
        4,
        is_support,
        "trendlines:pathfinding",
        score=score,
        r_squared=r_squared,
        metadata=metadata,
    )


def _make_boundary_result() -> BoundaryResult:
    support = _make_ray(
        is_support=True,
        score=0.91,
        r_squared=0.97,
        metadata={
            "inlier_ratio": 0.95,
            "coverage": 0.88,
            "cut_fraction": 0.02,
            "fit_start_index": 3,
            "fit_end_index": 15,
        },
    )
    resistance = _make_ray(
        is_support=False,
        score=0.83,
        r_squared=0.89,
        metadata={
            "inlier_ratio": 0.9,
            "coverage": 0.8,
            "cut_fraction": 0.05,
            "fit_start_index": 5,
            "fit_end_index": 14,
        },
    )
    return BoundaryResult(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=pd.Timestamp("2024-01-02"),
        active_support_rays=[support],
        active_resistance_rays=[resistance],
        quality_metrics=QualityMetrics(
            n_support_rays=1,
            n_resistance_rays=1,
            mean_score=0.87,
            mean_touch_count=4.0,
            mean_r_squared=0.93,
            hull_width_atr=2.4,
        ),
        is_valid=True,
    )


def test_build_monitor_snapshot_includes_best_ray_diagnostics():
    snapshot = build_monitor_snapshot(_make_boundary_result())

    assert snapshot["mean_score"] == 0.87
    assert snapshot["best_support_inlier_ratio"] == 0.95
    assert snapshot["best_support_fit_span_bars"] == 12.0
    assert snapshot["best_resistance_cut_fraction"] == 0.05


def test_compare_detects_best_ray_degradation():
    baseline = {
        "mean_score": 0.8,
        "best_support_coverage": 0.9,
        "best_support_cut_fraction": 0.0,
    }
    current = {
        "mean_score": 0.8,
        "best_support_coverage": 0.6,
        "best_support_cut_fraction": 0.08,
    }

    report = compare(current, baseline, threshold=0.15)

    assert "best_support_coverage" in report
    assert "best_support_cut_fraction" in report


def test_run_monitor_uses_trendlines_boundary_pipeline(monkeypatch, tmp_path):
    frame = pd.DataFrame(
        {
            "open": [1.0, 2.0, 3.0],
            "high": [1.5, 2.5, 3.5],
            "low": [0.5, 1.5, 2.5],
            "close": [1.2, 2.2, 3.2],
        },
        index=pd.date_range("2024-01-01", periods=3, freq="1h"),
    )
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(build_monitor_snapshot(_make_boundary_result())))
    captured = {}

    def fake_execute(df):
        captured["df_rows"] = len(df)
        return SimpleNamespace(is_valid=True, metadata={}), None

    def fake_boundary(df, *, asset, timeframe, trendline_result, trendline_config=None):
        del trendline_result, trendline_config
        captured["asset"] = asset
        captured["timeframe"] = timeframe
        captured["boundary_rows"] = len(df)
        return _make_boundary_result()

    monkeypatch.setattr(
        "libs.models.trendlines.workflows.monitoring.drift_monitor.execute_trendline_pipeline",
        fake_execute,
    )
    monkeypatch.setattr(
        "libs.models.trendlines.workflows.monitoring.drift_monitor.build_boundary_result_from_trendline_result",
        fake_boundary,
    )

    result = run_monitor("BTCUSDT", "1h", frame, str(baseline_path))

    assert result["status"] == "HEALTHY"
    assert captured == {
        "df_rows": 3,
        "asset": "BTCUSDT",
        "timeframe": "1h",
        "boundary_rows": 3,
    }