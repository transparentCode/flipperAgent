"""Tests for offline PriceAction guardrail candidates."""

from __future__ import annotations

from libs.models.regime_v2.scripts.price_action_guardrail_candidates import _parse_args
from libs.selection.regime_v2_price_action_guardrail import (
    build_price_action_guardrail_report,
    render_price_action_guardrail_report_markdown,
)


def _record(
    *,
    asset: str = "BTCUSDT",
    timeframe: str = "4h",
    baseline_model: str = "PriceAction",
    shadow_model: str | None = None,
    changed: bool = True,
    subset_only: bool = True,
    include_non_target_models: bool = False,
    baseline_direction: int = 1,
    regime_side: int = 1,
    confidence: float = 0.6,
    uncertainty: float = 0.3,
    trend_score: float = 0.1,
    breakout_score: float = 0.0,
    mean_reversion_score: float = 0.0,
    baseline_return: float = -0.02,
    lift: float = 0.02,
    label: str = "avoided_loss",
    active_playbooks: list[str] | None = None,
) -> dict:
    return {
        "asset": asset,
        "timeframe": timeframe,
        "baseline_selected_model": baseline_model,
        "shadow_selected_model": shadow_model,
        "selection_changed": changed,
        "shadow_subset_only": subset_only,
        "include_non_target_models": include_non_target_models,
        "target_models": ["Momentum", "TrendFollowing", "RegimePullbackScorer", "SqueezeBreakout"],
        "baseline_selected_direction": baseline_direction,
        "regime_side": regime_side,
        "confidence": confidence,
        "uncertainty": uncertainty,
        "trend_score": trend_score,
        "breakout_score": breakout_score,
        "mean_reversion_score": mean_reversion_score,
        "baseline_net_return": baseline_return,
        "shadow_minus_baseline": lift,
        "outcome_label": label,
        "active_playbooks": active_playbooks or [],
    }


def test_price_action_guardrail_report_finds_candidate_rules():
    records = [
        _record(asset="BTCUSDT", baseline_return=-0.02, lift=0.02),
        _record(asset="BTCUSDT", baseline_return=-0.03, lift=0.03),
        _record(asset="BTCUSDT", baseline_return=0.01, lift=-0.01, label="missed_win"),
        _record(asset="ETHUSDT", baseline_return=0.02, lift=-0.02, label="missed_win"),
        _record(baseline_model="Momentum", shadow_model="Momentum", changed=False, subset_only=False),
    ]

    report = build_price_action_guardrail_report(records, min_support=3, min_bad_rate=0.6)

    assert report["summary"]["total_records"] == 5
    assert report["summary"]["price_action_subset_removal_count"] == 4
    assert report["summary"]["candidate_rule_count"] >= 1
    first = report["candidate_rules"][0]
    assert first["count"] >= 3
    assert first["bad_rate"] >= 0.6
    assert first["avg_shadow_minus_baseline"] > 0.0


def test_price_action_guardrail_filters_non_price_action_rows():
    records = [
        _record(baseline_model="Momentum", shadow_model="Momentum", changed=False, subset_only=False),
        _record(shadow_model="Momentum"),
        _record(include_non_target_models=True),
    ]

    report = build_price_action_guardrail_report(records, min_support=1, min_bad_rate=0.1)

    assert report["summary"]["price_action_subset_removal_count"] == 0
    assert report["summary"]["candidate_rule_count"] == 0
    assert report["summary"]["overall_price_action"]["count"] == 0


def test_price_action_guardrail_diagnostics_include_buckets():
    report = build_price_action_guardrail_report(
        [
            _record(confidence=0.2, trend_score=0.0),
            _record(confidence=0.8, trend_score=0.2),
        ],
        min_support=1,
        min_bad_rate=0.1,
    )

    diagnostics = report["diagnostics"]
    assert "confidence:(-inf,0.3]" in diagnostics["confidence_bucket"]
    assert "confidence:>0.7" in diagnostics["confidence_bucket"]
    assert "trend:zero" in diagnostics["trend_score_bucket"]
    assert "trend:(0.18,0.24]" in diagnostics["trend_score_bucket"]


def test_render_price_action_guardrail_markdown_contains_candidate_table():
    report = build_price_action_guardrail_report(
        [_record(), _record(baseline_return=0.01, lift=-0.01, label="missed_win")],
        min_support=1,
        min_bad_rate=0.1,
    )

    md = render_price_action_guardrail_report_markdown(report)

    assert "# RegimeV2 Phase 6F PriceAction Guardrail Candidate" in md
    assert "## Candidate Rules" in md
    assert "| Rank | Condition |" in md


def test_price_action_guardrail_cli_parse_args():
    args = _parse_args(
        [
            "--outcomes",
            "research/custom.jsonl",
            "--min-support",
            "12",
            "--min-bad-rate",
            "0.6",
            "--min-avg-lift",
            "0.001",
            "--output-json",
            "research/guardrail.json",
            "--output-md",
            "research/guardrail.md",
        ]
    )

    assert args.outcomes == "research/custom.jsonl"
    assert args.min_support == 12
    assert args.min_bad_rate == 0.6
    assert args.min_avg_lift == 0.001
    assert args.output_json == "research/guardrail.json"
    assert args.output_md == "research/guardrail.md"


def test_price_action_guardrail_cli_defaults():
    args = _parse_args([])

    assert args.outcomes == "research/regime_v2_shadow_outcomes.jsonl"
    assert args.min_support == 10
    assert args.min_bad_rate == 0.55
    assert args.min_avg_lift == 0.0
