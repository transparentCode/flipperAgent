"""Tests for RegimeV2 Phase 5 shadow-decision replay reports."""

from __future__ import annotations

import json

from libs.models.regime_v2.scripts.report_shadow_decisions import _parse_args
from libs.selection.regime_v2_shadow_report import (
    build_regime_v2_shadow_report,
    load_regime_v2_shadow_decisions,
    render_regime_v2_shadow_report_markdown,
    run_regime_v2_shadow_report,
)


def _record(
    *,
    asset: str = "BTCUSDT",
    timeframe: str = "1h",
    baseline: str = "PriceAction",
    shadow: str = "Momentum",
    changed: bool = True,
    gate_reason: str = "active",
    playbooks: list[str] | None = None,
    edge_delta: float | None = 0.1,
) -> dict:
    active_playbooks = ["trend"] if playbooks is None else playbooks
    return {
        "schema_version": 1,
        "record_type": "regime_v2_shadow_decision",
        "asset": asset,
        "timeframe": timeframe,
        "timestamp": 1000.0,
        "selected_count": 2,
        "baseline_selected_model": baseline,
        "shadow_selected_model": shadow,
        "selection_changed": changed,
        "reason": "shadow_changed_top_pick" if changed else "top_pick_aligned_with_regime",
        "gate_active": gate_reason == "active",
        "gate_reason": gate_reason,
        "active_playbooks": active_playbooks,
        "shadow_subset_name": "validated_phase5a_subset",
        "shadow_subset_only": True,
        "include_non_target_models": False,
        "baseline_selection_score": 0.9,
        "shadow_selection_score": 0.8,
        "edge_delta": edge_delta,
        "trend_score": 0.5,
        "breakout_score": 0.4,
        "mean_reversion_score": 0.3,
        "confidence": 0.7,
        "uncertainty": 0.2,
        "baseline_candidate_count": 3,
        "shadow_candidate_count": 2,
        "shadow_selected_count": 2,
        "target_candidate_count": 2,
        "target_models": ["Momentum", "TrendFollowing", "RegimePullbackScorer", "SqueezeBreakout"],
        "aligned_target_models": [shadow] if shadow else [],
        "conflict_target_models": [],
        "candidate_playbooks": {"Momentum": "trend", "SqueezeBreakout": "breakout"},
    }


def test_load_shadow_decisions_counts_invalid_jsonl_rows(tmp_path):
    path = tmp_path / "shadow.jsonl"
    records = [_record(), _record(asset="ETHUSDT", timeframe="4h", baseline="Momentum", shadow="Momentum", changed=False)]
    path.write_text(
        json.dumps(records[0])
        + "\n"
        + "not-json\n"
        + json.dumps(records[1])
        + "\n"
        + "[]\n",
        encoding="utf-8",
    )

    loaded, invalid = load_regime_v2_shadow_decisions(path)

    assert len(loaded) == 2
    assert invalid == 2
    assert loaded[0]["baseline_selected_model"] == "PriceAction"


def test_run_shadow_report_filters_and_aggregates(tmp_path):
    path = tmp_path / "shadow.jsonl"
    rows = [
        _record(asset="BTCUSDT", timeframe="1h", baseline="PriceAction", shadow="Momentum", changed=True, playbooks=["trend", "breakout"], edge_delta=-0.1),
        _record(asset="BTCUSDT", timeframe="1h", baseline="TrendFollowing", shadow="Momentum", changed=True, playbooks=["trend"], edge_delta=0.2),
        _record(asset="ETHUSDT", timeframe="4h", baseline="Momentum", shadow="Momentum", changed=False, gate_reason="inactive_playbook_policy", playbooks=[], edge_delta=0.0),
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    report = run_regime_v2_shadow_report(path, asset="BTCUSDT", timeframe="1h")

    summary = report["summary"]
    assert summary["total_records_read"] == 3
    assert summary["records_after_filter"] == 2
    assert summary["selection_changed_count"] == 2
    assert summary["selection_changed_rate"] == 1.0
    assert summary["gate_active_count"] == 2
    assert summary["avg_edge_delta"] == 0.05
    assert report["distributions"]["active_playbooks"] == {"breakout": 1, "trend": 2}
    assert report["distributions"]["asset_timeframe"] == {"BTCUSDT|1h": 2}
    assert report["changed_pick_groups"][0]["count"] == 1
    assert {row["baseline_selected_model"] for row in report["changed_pick_groups"]} == {"PriceAction", "TrendFollowing"}


def test_shadow_report_splits_active_changes_from_inactive_subset_rows():
    records = [
        _record(baseline="Momentum", shadow="SqueezeBreakout", changed=True, gate_reason="active", playbooks=["trend", "breakout"], edge_delta=0.2),
        _record(baseline="PriceAction", shadow=None, changed=True, gate_reason="inactive_playbook_policy", playbooks=[], edge_delta=None),
        _record(baseline="TrendFollowing", shadow="TrendFollowing", changed=False, gate_reason="inactive_playbook_policy", playbooks=[], edge_delta=0.0),
    ]

    report = build_regime_v2_shadow_report(records)
    summary = report["summary"]

    assert summary["selection_changed_count"] == 2
    assert summary["gate_active_count"] == 1
    assert summary["gate_active_changed_count"] == 1
    assert summary["gate_active_changed_rate"] == 1.0
    assert summary["gate_inactive_count"] == 2
    assert summary["gate_inactive_changed_count"] == 1
    assert summary["gate_inactive_changed_rate"] == 0.5
    assert summary["inactive_policy_count"] == 2
    assert summary["inactive_policy_changed_count"] == 1
    assert summary["inactive_policy_changed_rate"] == 0.5
    assert summary["subset_only_changed_count"] == 1
    assert summary["price_action_subset_exclusion_count"] == 1


def test_shadow_report_handles_empty_missing_log(tmp_path):
    report = run_regime_v2_shadow_report(tmp_path / "missing.jsonl")

    assert report["summary"]["total_records_read"] == 0
    assert report["summary"]["records_after_filter"] == 0
    assert report["summary"]["selection_changed_rate"] is None
    assert report["model_pair_summary"] == []


def test_render_shadow_report_markdown_contains_core_sections():
    report = build_regime_v2_shadow_report([_record(playbooks=["trend", "mean_reversion"])], source_path="shadow.jsonl")

    md = render_regime_v2_shadow_report_markdown(report)

    assert "# RegimeV2 Phase 5 Shadow Replay Report" in md
    assert "Selection changed: 1 (1.0)" in md
    assert "mean_reversion: 1" in md
    assert "| PriceAction | Momentum | 1 |" in md


def test_shadow_report_cli_parse_args():
    args = _parse_args([
        "--log",
        "logs/custom.jsonl",
        "--asset",
        "btcusdt",
        "--timeframe",
        "4h",
        "--output-json",
        "research/shadow.json",
        "--output-md",
        "research/shadow.md",
    ])

    assert args.log == "logs/custom.jsonl"
    assert args.asset == "btcusdt"
    assert args.timeframe == "4h"
    assert args.output_json == "research/shadow.json"
    assert args.output_md == "research/shadow.md"
