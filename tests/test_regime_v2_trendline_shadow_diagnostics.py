from __future__ import annotations

import pytest

from libs.models.regime_v2.scripts.report_trendline_shadow_diagnostics import _parse_args
from libs.selection.regime_v2_trendline_shadow_diagnostics import (
    build_trendline_shadow_diagnostics,
    render_trendline_shadow_diagnostics_markdown,
)


def _record(
    *,
    asset: str = "BTCUSDT",
    timeframe: str = "1h",
    shadow_model: str = "Momentum",
    changed: bool = True,
    position: str = "inside_channel",
    interaction: str = "NONE",
    quality: float = 0.72,
    edge_delta: float | None = 0.1,
    near_support: bool = False,
    near_resistance: bool = False,
    mid_noise: bool = False,
    above_channel: bool = False,
    below_channel: bool = False,
    inside_channel: bool = True,
    convergence: float = 0.05,
    persistence_bias: float = 0.2,
    shadow_lift: float | None = None,
    outcome_label: str | None = None,
) -> dict:
    risk_context = {
        "near_support": "near_support_reversal_context",
        "near_resistance": "near_resistance_reversal_context",
        "mid_channel_noise": "mid_channel_noise",
        "upper_channel_pressure": "upper_channel_pressure_watch",
        "lower_channel_pressure": "lower_channel_pressure_watch",
        "above_channel": "above_channel_breakout_context",
        "below_channel": "below_channel_breakdown_context",
        "inside_channel": "inside_channel_context",
    }.get(position, "valid_structure")
    confidence_annotation = "caution" if risk_context == "mid_channel_noise" else "neutral"
    record = {
        "record_type": "regime_v2_shadow_decision",
        "asset": asset,
        "timeframe": timeframe,
        "timestamp": 1000.0,
        "baseline_selected_model": "PriceAction",
        "shadow_selected_model": shadow_model,
        "selection_changed": changed,
        "gate_active": True,
        "edge_delta": edge_delta,
        "trendline_valid": 1.0,
        "trendline_interaction": interaction,
        "trendline_structure_state": "closed_channel",
        "trendline_market_position_state": position,
        "trendline_has_closed_channel": 1.0,
        "trendline_inside_channel": 1.0 if inside_channel else 0.0,
        "trendline_above_channel": 1.0 if above_channel else 0.0,
        "trendline_below_channel": 1.0 if below_channel else 0.0,
        "trendline_near_support": 1.0 if near_support else 0.0,
        "trendline_near_resistance": 1.0 if near_resistance else 0.0,
        "trendline_mid_channel_noise": 1.0 if mid_noise else 0.0,
        "trendline_hull_width_atr": 2.5,
        "trendline_hull_position": 0.5,
        "trendline_channel_compression_score": 0.2,
        "trendline_support_quality_score": min(1.0, quality + 0.05),
        "trendline_resistance_quality_score": max(0.0, quality - 0.05),
        "trendline_mean_normalized_quality": quality,
        "trendline_history_count": 3.0,
        "trendline_interaction_transition": "NONE->NONE",
        "trendline_market_position_transition": f"inside_channel->{position}",
        "trendline_ray_persistence_bias": persistence_bias,
        "trendline_hull_convergence_rate": convergence,
        "trendline_hull_expansion_rate": 0.0,
        "trendline_risk_context": risk_context,
        "trendline_confidence_annotation": confidence_annotation,
        "trendline_annotation_reason": f"test_{risk_context}",
        "trendline_no_trade_warning": 1.0 if risk_context == "mid_channel_noise" else 0.0,
        "trendline_context": {"trendline_valid": 1.0, "trendline_market_position_state": position},
    }
    if shadow_lift is not None:
        record["shadow_minus_baseline"] = shadow_lift
        record["outcome_label"] = outcome_label or ("improved_pick" if shadow_lift > 0 else "worsened_pick")
    return record


def test_trendline_shadow_diagnostics_summarizes_context_and_changes():
    rows = [
        _record(position="near_support", near_support=True, quality=0.8, edge_delta=0.2, shadow_lift=0.03),
        _record(position="mid_channel_noise", mid_noise=True, quality=0.3, edge_delta=-0.1, shadow_lift=-0.02),
        _record(position="inside_channel", changed=False, quality=0.6, edge_delta=0.0, shadow_lift=0.0, outcome_label="unchanged"),
        {"asset": "BTCUSDT", "timeframe": "1h", "selection_changed": True},
    ]

    report = build_trendline_shadow_diagnostics(rows, source_path="shadow.jsonl")
    summary = report["summary"]

    assert report["phase"] == "phase_tl_h8_trendline_shadow_diagnostics"
    assert summary["records_after_filter"] == 4
    assert summary["trendline_context_count"] == 3
    assert summary["trendline_context_changed_count"] == 2
    assert summary["trendline_context_changed_rate"] == 2 / 3
    assert summary["avg_trendline_mean_quality"] == pytest.approx((0.8 + 0.3 + 0.6) / 3)
    assert summary["outcome_labeled_context_count"] == 3
    assert summary["avg_shadow_minus_baseline"] == pytest.approx((0.03 - 0.02 + 0.0) / 3)
    assert summary["changed_avg_shadow_minus_baseline"] == pytest.approx((0.03 - 0.02) / 2)
    assert summary["changed_positive_shadow_lift_rate"] == 0.5
    assert report["distributions"]["trendline_market_position_state"] == {
        "inside_channel": 1,
        "mid_channel_noise": 1,
        "near_support": 1,
    }
    assert report["distributions"]["selection_changed_by_market_position"]["near_support"]["selection_changed_rate"] == 1.0
    assert report["distributions"]["outcome_label"] == {"improved_pick": 1, "unchanged": 1, "worsened_pick": 1}
    assert report["distributions"]["trendline_risk_context"] == {
        "inside_channel_context": 1,
        "mid_channel_noise": 1,
        "near_support_reversal_context": 1,
    }
    assert report["distributions"]["trendline_confidence_annotation"] == {"caution": 1, "neutral": 2}
    assert report["risk_context_groups"][0]["avg_shadow_minus_baseline"] is not None
    assert report["market_position_groups"][0]["avg_shadow_minus_baseline"] is not None


def test_trendline_shadow_diagnostics_quality_buckets_and_questions():
    rows = [
        _record(position="near_resistance", near_resistance=True, quality=0.85, shadow_model="SqueezeBreakout", above_channel=True, inside_channel=False, shadow_lift=0.04),
        _record(position="upper_channel_pressure", quality=0.65, shadow_model="SqueezeBreakout", edge_delta=0.3, shadow_lift=-0.01),
        _record(position="mid_channel_noise", mid_noise=True, quality=0.2, shadow_model="Momentum", edge_delta=-0.2, shadow_lift=-0.03),
    ]

    report = build_trendline_shadow_diagnostics(rows)
    questions = report["candidate_questions"]

    assert report["distributions"]["quality_bucket"] == {"high": 1, "low": 1, "medium": 1}
    assert questions["changed_near_support_or_resistance_count"] == 1
    assert questions["changed_mid_channel_noise_count"] == 1
    assert questions["breakout_shadow_count"] == 2
    assert questions["breakout_shadow_above_channel_count"] == 1
    assert questions["breakout_shadow_pressure_only_count"] == 1
    assert questions["high_quality_changed_count"] == 1
    assert report["context_flags"]["trendline_mid_channel_noise"]["count"] == 1
    assert questions["mid_channel_noise_avg_shadow_lift"] == -0.03
    assert questions["upper_channel_pressure_avg_shadow_lift"] == -0.01
    assert questions["near_support_or_resistance_avg_shadow_lift"] == 0.04


def test_trendline_shadow_diagnostics_filters_asset_timeframe():
    rows = [
        _record(asset="BTCUSDT", timeframe="1h"),
        _record(asset="ETHUSDT", timeframe="4h"),
    ]

    report = build_trendline_shadow_diagnostics(rows, asset="ethusdt", timeframe="4h")

    assert report["summary"]["records_after_filter"] == 1
    assert report["summary"]["asset_filter"] == "ETHUSDT"
    assert report["summary"]["timeframe_filter"] == "4h"
    assert report["distributions"]["asset_timeframe"] == {"ETHUSDT|4h": 1}


def test_render_trendline_shadow_diagnostics_markdown_contains_sections():
    report = build_trendline_shadow_diagnostics([_record(position="near_support", near_support=True)])

    md = render_trendline_shadow_diagnostics_markdown(report)

    assert "# RegimeV2 Trendline Shadow Diagnostics" in md
    assert "## Market Position Groups" in md
    assert "## Risk Context Annotations" in md
    assert "## Quality Buckets" in md
    assert "## Diagnostic Questions" in md
    assert "near_support" in md


def test_trendline_shadow_diagnostics_cli_parse_args():
    args = _parse_args(
        [
            "--log",
            "logs/custom.jsonl",
            "--asset",
            "btcusdt",
            "--timeframe",
            "4h",
            "--output-json",
            "research/tl.json",
            "--output-md",
            "research/tl.md",
        ]
    )

    assert args.log == "logs/custom.jsonl"
    assert args.asset == "btcusdt"
    assert args.timeframe == "4h"
    assert args.output_json == "research/tl.json"
    assert args.output_md == "research/tl.md"
