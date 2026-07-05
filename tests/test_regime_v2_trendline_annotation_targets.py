from __future__ import annotations

import pytest

from libs.models.regime_v2.scripts.report_trendline_annotation_targets import _parse_args, _parse_targets
from libs.selection.regime_v2_trendline_annotation_targets import (
    AnnotationTargetThresholds,
    build_trendline_annotation_target_report,
    render_trendline_annotation_target_markdown,
)


def _record(
    *,
    asset: str = "BTCUSDT",
    timeframe: str = "4h",
    risk: str = "upper_channel_pressure_watch",
    annotation: str = "breakout_watch",
    pressure: float = 1.0,
    lift: float = 0.01,
    outcome: str = "avoided_loss",
    model: str = "Momentum",
    quality: float = 0.9,
    resistance_quality: float = 0.9,
    persistence_bias: float = 0.1,
    expansion_rate: float = 0.05,
    interaction: str = "STRUCTURAL_BREAKOUT",
    mid_noise: float = 0.0,
) -> dict:
    return {
        "asset": asset,
        "timeframe": timeframe,
        "trendline_risk_context": risk,
        "trendline_confidence_annotation": annotation,
        "trendline_pressure_watch": pressure,
        "trendline_mean_normalized_quality": quality,
        "trendline_resistance_quality_score": resistance_quality,
        "trendline_ray_persistence_bias": persistence_bias,
        "trendline_hull_expansion_rate": expansion_rate,
        "trendline_interaction": interaction,
        "trendline_mid_channel_noise": mid_noise,
        "shadow_minus_baseline": lift,
        "outcome_label": outcome,
        "shadow_selected_model": model,
    }


def test_annotation_target_report_marks_ready_and_immature_targets():
    rows = [
        _record(lift=0.03),
        _record(lift=0.02),
        _record(lift=-0.01, outcome="missed_win"),
        _record(risk="mid_channel_noise", annotation="caution", pressure=0.0, lift=-0.02, outcome="missed_win"),
    ]

    report = build_trendline_annotation_target_report(
        rows,
        targets=[
            ("trendline_risk_context", "upper_channel_pressure_watch"),
            ("trendline_risk_context", "mid_channel_noise"),
        ],
        thresholds=AnnotationTargetThresholds(min_samples=3, min_positive_lift_rate=0.5, min_avg_shadow_lift=0.0),
    )

    summary = report["summary"]
    assert summary["records_after_filter"] == 4
    assert summary["labeled_count"] == 4
    assert summary["candidate_ready_count"] == 1
    assert summary["needs_more_evidence_count"] == 1

    ready = report["candidate_ready_targets"][0]
    assert ready["field"] == "trendline_risk_context"
    assert ready["value"] == "upper_channel_pressure_watch"
    assert ready["count"] == 3
    assert ready["avg_shadow_lift"] == pytest.approx((0.03 + 0.02 - 0.01) / 3)
    assert ready["positive_shadow_lift_rate"] == 2 / 3
    assert ready["asset_timeframe"] == {"BTCUSDT|4h": 3}
    assert ready["outcome_label"] == {"avoided_loss": 2, "missed_win": 1}

    immature = report["needs_more_evidence_targets"][0]
    assert immature["value"] == "mid_channel_noise"
    assert immature["additional_samples_needed"] == 2
    assert immature["evidence_status"] == "needs_more_evidence"


def test_annotation_target_report_filters_asset_timeframe_and_numeric_target():
    rows = [
        _record(asset="BTCUSDT", timeframe="4h", pressure=1.0, lift=0.01),
        _record(asset="ETHUSDT", timeframe="4h", pressure=1.0, lift=0.02),
        _record(asset="BTCUSDT", timeframe="1h", pressure=0.0, lift=-0.01),
    ]

    report = build_trendline_annotation_target_report(
        rows,
        targets=[("trendline_pressure_watch", 1.0)],
        thresholds=AnnotationTargetThresholds(min_samples=1),
        asset="btcusdt",
        timeframe="4h",
    )

    target = report["targets"][0]
    assert report["summary"]["records_after_filter"] == 1
    assert target["count"] == 1
    assert target["evidence_status"] == "candidate_ready"


def test_annotation_target_report_derives_strict_breakout_fields_from_legacy_rows():
    rows = [
        _record(lift=0.02),
        _record(lift=-0.01, outcome="missed_win", persistence_bias=-0.2, expansion_rate=0.0, interaction="NONE"),
        _record(annotation="continuation_watch", risk="above_channel_breakout_context", pressure=0.0, lift=0.01),
    ]

    report = build_trendline_annotation_target_report(
        rows,
        targets=[
            ("trendline_breakout_watch_high_quality", 1.0),
            ("trendline_breakout_watch_positive_persistence", 1.0),
            ("trendline_breakout_watch_hull_expansion", 1.0),
            ("trendline_breakout_watch_confirmed_interaction", 1.0),
            ("trendline_breakout_watch_strict_context", "breakout_watch_strict"),
        ],
        thresholds=AnnotationTargetThresholds(min_samples=1, min_positive_lift_rate=0.0),
    )

    counts = {(target["field"], target["value"]): target["count"] for target in report["targets"]}
    assert counts[("trendline_breakout_watch_high_quality", 1.0)] == 2
    assert counts[("trendline_breakout_watch_positive_persistence", 1.0)] == 1
    assert counts[("trendline_breakout_watch_hull_expansion", 1.0)] == 1
    assert counts[("trendline_breakout_watch_confirmed_interaction", 1.0)] == 1
    assert counts[("trendline_breakout_watch_strict_context", "breakout_watch_strict")] == 1


def test_annotation_target_markdown_contains_target_table():
    report = build_trendline_annotation_target_report(
        [_record(lift=0.02), _record(lift=-0.01)],
        thresholds=AnnotationTargetThresholds(min_samples=2, min_positive_lift_rate=0.5),
    )

    md = render_trendline_annotation_target_markdown(report)

    assert "# RegimeV2 Trendline Annotation Target Report" in md
    assert "## Targets" in md
    assert "trendline_risk_context" in md
    assert "upper_channel_pressure_watch" in md


def test_annotation_target_cli_parse_args_and_targets():
    args = _parse_args(
        [
            "--log",
            "research/tl13/eval.jsonl",
            "--asset",
            "btcusdt",
            "--timeframe",
            "4h",
            "--target",
            "trendline_risk_context=upper_channel_pressure_watch",
            "--target",
            "trendline_pressure_watch=true",
            "--min-samples",
            "25",
            "--min-positive-lift-rate",
            "0.55",
            "--min-avg-shadow-lift",
            "0.001",
            "--output-json",
            "research/tl14/targets.json",
            "--output-md",
            "research/tl14/targets.md",
        ]
    )

    assert args.log == "research/tl13/eval.jsonl"
    assert args.asset == "btcusdt"
    assert args.timeframe == "4h"
    assert args.min_samples == 25
    assert args.min_positive_lift_rate == 0.55
    assert args.min_avg_shadow_lift == 0.001
    assert _parse_targets(args.target) == [
        ("trendline_risk_context", "upper_channel_pressure_watch"),
        ("trendline_pressure_watch", 1.0),
    ]
