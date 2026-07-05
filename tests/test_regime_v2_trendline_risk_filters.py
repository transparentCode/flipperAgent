from __future__ import annotations

import pytest

from libs.selection.regime_v2_trendline_risk_filters import (
    RiskFilterThresholds,
    build_trendline_risk_filter_report,
    render_trendline_risk_filter_markdown,
)


def _record(
    *,
    changed: bool = True,
    lift: float = -0.01,
    risk: str = "mid_channel_noise",
    annotation: str = "caution",
    mid_noise: float = 1.0,
    no_trade: float = 1.0,
    pressure: float = 0.0,
    asset: str = "BTCUSDT",
    timeframe: str = "4h",
) -> dict:
    return {
        "asset": asset,
        "timeframe": timeframe,
        "selection_changed": changed,
        "shadow_minus_baseline": lift,
        "trendline_risk_context": risk,
        "trendline_confidence_annotation": annotation,
        "trendline_mid_channel_noise": mid_noise,
        "trendline_no_trade_warning": no_trade,
        "trendline_pressure_watch": pressure,
        "outcome_label": "missed_win" if lift < 0 else "avoided_loss",
        "shadow_selected_model": "Momentum",
    }


def test_risk_filter_report_marks_candidate_warning_context():
    rows = [
        _record(lift=-0.02),
        _record(lift=-0.01),
        _record(lift=0.03),
        _record(changed=False, lift=0.05),
    ]

    report = build_trendline_risk_filter_report(
        rows,
        filters=[("trendline_mid_channel_noise", 1.0)],
        thresholds=RiskFilterThresholds(min_changed_samples=3, min_bad_change_rate=0.60, max_avg_changed_lift=0.0),
    )

    item = report["filters"][0]
    assert report["summary"]["changed_labeled_count"] == 3
    assert item["changed_count"] == 3
    assert item["avg_changed_shadow_lift"] == pytest.approx(0.0)
    assert item["bad_change_rate"] == 2 / 3
    assert item["avg_loss_avoided_when_bad"] == pytest.approx(0.015)
    assert item["risk_filter_status"] == "candidate_ready"


def test_risk_filter_report_rejects_positive_context():
    rows = [
        _record(lift=0.02, pressure=1.0, risk="upper_channel_pressure_watch", annotation="breakout_watch", mid_noise=0.0, no_trade=0.0),
        _record(lift=0.01, pressure=1.0, risk="upper_channel_pressure_watch", annotation="breakout_watch", mid_noise=0.0, no_trade=0.0),
        _record(lift=-0.01, pressure=1.0, risk="upper_channel_pressure_watch", annotation="breakout_watch", mid_noise=0.0, no_trade=0.0),
    ]

    report = build_trendline_risk_filter_report(
        rows,
        filters=[("trendline_pressure_watch", 1.0)],
        thresholds=RiskFilterThresholds(min_changed_samples=3, min_bad_change_rate=0.60, max_avg_changed_lift=0.0),
    )

    item = report["filters"][0]
    assert item["changed_count"] == 3
    assert item["bad_change_rate"] == 1 / 3
    assert item["avg_changed_shadow_lift"] > 0.0
    assert item["risk_filter_status"] == "needs_more_evidence"


def test_risk_filter_report_filters_asset_timeframe_and_markdown():
    rows = [
        _record(asset="BTCUSDT", timeframe="4h", lift=-0.01),
        _record(asset="ETHUSDT", timeframe="1h", lift=-0.01),
    ]

    report = build_trendline_risk_filter_report(
        rows,
        filters=[("trendline_no_trade_warning", 1.0)],
        thresholds=RiskFilterThresholds(min_changed_samples=1, min_bad_change_rate=0.5),
        asset="btcusdt",
        timeframe="4h",
    )
    md = render_trendline_risk_filter_markdown(report)

    assert report["summary"]["records_after_filter"] == 1
    assert report["filters"][0]["asset_timeframe"] == {"BTCUSDT|4h": 1}
    assert "# RegimeV2 Trendline Risk Filter Report" in md
    assert "trendline_no_trade_warning" in md
