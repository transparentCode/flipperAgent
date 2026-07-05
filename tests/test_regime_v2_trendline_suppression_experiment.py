from __future__ import annotations

import pytest

from libs.selection.regime_v2_trendline_suppression_experiment import (
    SuppressionThresholds,
    build_trendline_suppression_experiment,
    render_trendline_suppression_experiment_markdown,
)


def _record(
    *,
    changed: bool = True,
    lift: float = -0.01,
    mid_noise: float = 1.0,
    no_trade: float = 1.0,
    annotation: str = "caution",
    asset: str = "BTCUSDT",
    timeframe: str = "4h",
) -> dict:
    return {
        "asset": asset,
        "timeframe": timeframe,
        "selection_changed": changed,
        "shadow_minus_baseline": lift,
        "trendline_mid_channel_noise": mid_noise,
        "trendline_no_trade_warning": no_trade,
        "trendline_confidence_annotation": annotation,
        "outcome_label": "missed_win" if lift < 0 else "avoided_loss",
        "shadow_selected_model": "Momentum",
    }


def test_suppression_experiment_improves_when_warning_catches_bad_changes():
    rows = [
        _record(lift=-0.03),
        _record(lift=-0.02),
        _record(lift=0.01),
        _record(lift=0.04, mid_noise=0.0, no_trade=0.0, annotation="neutral"),
    ]

    report = build_trendline_suppression_experiment(
        rows,
        filters=[("trendline_mid_channel_noise", 1.0)],
        thresholds=SuppressionThresholds(min_suppressed_samples=3, min_loss_saved_rate=0.6, min_net_lift_delta=0.0),
        include_combined=False,
    )

    item = report["experiments"][0]
    assert item["suppressed_count"] == 3
    assert item["loss_saved_count"] == 2
    assert item["missed_good_count"] == 1
    assert item["loss_saved_rate"] == 2 / 3
    assert item["loss_saved_total"] == pytest.approx(0.05)
    assert item["good_lift_missed_total"] == pytest.approx(0.01)
    assert item["net_lift_delta_all_rows"] == pytest.approx(0.04 / 4)
    assert item["experiment_status"] == "candidate_ready"


def test_suppression_experiment_rejects_warning_that_suppresses_good_changes():
    rows = [
        _record(lift=0.02),
        _record(lift=0.03),
        _record(lift=-0.01),
    ]

    report = build_trendline_suppression_experiment(
        rows,
        filters=[("trendline_no_trade_warning", 1.0)],
        thresholds=SuppressionThresholds(min_suppressed_samples=3, min_loss_saved_rate=0.6),
        include_combined=False,
    )

    item = report["experiments"][0]
    assert item["suppressed_count"] == 3
    assert item["loss_saved_rate"] == 1 / 3
    assert item["net_lift_delta_all_rows"] < 0.0
    assert item["experiment_status"] == "needs_more_evidence"


def test_suppression_experiment_combines_filters_without_double_counting():
    rows = [
        _record(lift=-0.02, mid_noise=1.0, no_trade=1.0),
        _record(lift=-0.01, mid_noise=0.0, no_trade=1.0),
        _record(lift=0.03, mid_noise=1.0, no_trade=0.0),
    ]

    report = build_trendline_suppression_experiment(
        rows,
        filters=[("trendline_mid_channel_noise", 1.0), ("trendline_no_trade_warning", 1.0)],
        thresholds=SuppressionThresholds(min_suppressed_samples=1, min_loss_saved_rate=0.0),
        include_combined=True,
    )

    combined = report["experiments"][-1]
    assert combined["name"] == "combined_any_candidate_warning"
    assert combined["suppressed_count"] == 3
    assert combined["loss_saved_total"] == pytest.approx(0.03)
    assert combined["good_lift_missed_total"] == pytest.approx(0.03)


def test_suppression_experiment_filters_asset_timeframe_and_markdown():
    rows = [
        _record(asset="BTCUSDT", timeframe="4h", lift=-0.02),
        _record(asset="ETHUSDT", timeframe="1h", lift=-0.02),
    ]

    report = build_trendline_suppression_experiment(
        rows,
        filters=[("trendline_mid_channel_noise", 1.0)],
        thresholds=SuppressionThresholds(min_suppressed_samples=1, min_loss_saved_rate=0.5),
        asset="btcusdt",
        timeframe="4h",
    )
    md = render_trendline_suppression_experiment_markdown(report)

    assert report["summary"]["records_after_filter"] == 1
    assert report["experiments"][0]["asset_timeframe"] == {"BTCUSDT|4h": 1}
    assert "# RegimeV2 Trendline Suppression Experiment" in md
    assert "trendline_mid_channel_noise" in md
