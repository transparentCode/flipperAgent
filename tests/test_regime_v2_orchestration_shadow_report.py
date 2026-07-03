"""Tests for Phase 8B orchestration shadow report."""

from __future__ import annotations

import json

from libs.models.regime_v2.evaluation.playbook_orchestration_shadow_report import (
    build_orchestration_shadow_report,
    render_orchestration_shadow_report_markdown,
    run_orchestration_shadow_report,
)
from libs.models.regime_v2.scripts.report_orchestration_shadow import _parse_args


def _shadow_report():
    return {
        "phase": "phase_5_shadow_replay",
        "summary": {
            "source_path": "shadow.jsonl",
            "total_records_read": 1,
            "invalid_record_count": 0,
            "records_after_filter": 1,
            "selection_changed_count": 1,
            "selection_changed_rate": 1.0,
            "gate_active_count": 1,
            "gate_active_rate": 1.0,
        },
        "distributions": {"active_playbooks": {"trend": 1}},
        "changed_pick_groups": [],
        "model_pair_summary": [],
    }


def _orchestration_payload():
    return {
        "report": {
            "summary": {
                "row_count": 2160,
                "routeable_count": 164,
                "transition_postures": ["frozen_diagnostic"],
                "transition_runtime_enabled_count": 0,
                "transition_promotion_ready_count": 0,
                "recommended_next_step": "resume_base_playbook_orchestration_and_shadow_reporting",
            }
        }
    }


def test_orchestration_shadow_report_attaches_frozen_posture():
    report = build_orchestration_shadow_report(_shadow_report(), _orchestration_payload())
    md = render_orchestration_shadow_report_markdown(report)

    assert report["phase"] == "phase_8b_orchestration_shadow_report"
    assert report["summary"]["orchestration_attached"] is True
    assert report["summary"]["transition_postures"] == ["frozen_diagnostic"]
    assert report["summary"]["transition_runtime_enabled_count"] == 0
    assert report["summary"]["runtime_action"] == "base_shadow_report_with_transition_diagnostics_frozen"
    assert "Phase 8B Orchestration Shadow Report" in md


def test_orchestration_shadow_runner_reads_shadow_and_orchestration_files(tmp_path):
    log = tmp_path / "shadow.jsonl"
    log.write_text(
        json.dumps({
            "asset": "BTCUSDT",
            "timeframe": "1h",
            "baseline_selected_model": "PriceAction",
            "shadow_selected_model": "Momentum",
            "selection_changed": True,
            "gate_active": True,
            "gate_reason": "active",
            "active_playbooks": ["trend"],
        }) + "\n",
        encoding="utf-8",
    )
    gate = tmp_path / "gate.json"
    gate.write_text(json.dumps(_orchestration_payload()), encoding="utf-8")

    report = run_orchestration_shadow_report(log, orchestration_json_path=gate, asset="BTCUSDT", timeframe="1h")

    assert report["summary"]["shadow_records_after_filter"] == 1
    assert report["summary"]["orchestration_row_count"] == 2160


def test_orchestration_shadow_cli_defaults_and_args():
    args = _parse_args(["--log", "x.jsonl", "--asset", "ETHUSDT", "--timeframe", "1h"])
    assert args.log == "x.jsonl"
    assert args.asset == "ETHUSDT"
    assert args.timeframe == "1h"

    defaults = _parse_args([])
    assert defaults.orchestration_json.endswith("phase8a_playbook_orchestration_gate.json")
    assert defaults.output_json.endswith("phase8b_orchestration_shadow_report.json")
