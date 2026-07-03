"""Tests for Phase 8A playbook orchestration gate."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_orchestration_gate import (
    build_playbook_orchestration_frame,
    build_playbook_orchestration_gate_report,
    render_playbook_orchestration_gate_markdown,
)
from libs.models.regime_v2.scripts.report_playbook_orchestration_gate import _parse_args


def test_orchestration_gate_freezes_transition_branch():
    states = pd.DataFrame(
        [
            {"playbook_state": "BREAKOUT_SETUP", "playbook_state_is_executable": False, "playbook_state_group": "wait"},
            {"playbook_state": "TREND_CONTINUATION", "playbook_state_is_executable": True, "playbook_state_group": "execute"},
        ]
    )
    gate = {"summary": {"decision": "freeze_transition_micro_states_diagnostic", "promotion_ready": False, "runtime_enabled_count": 0, "blockers": ["support"]}}

    frame = build_playbook_orchestration_frame(states, gate)
    report = build_playbook_orchestration_gate_report(frame, gate, asset="BNBUSDT", timeframe="1h")
    md = render_playbook_orchestration_gate_markdown(report)

    assert set(frame["playbook_orchestration_transition_posture"]) == {"frozen_diagnostic"}
    assert set(frame["playbook_orchestration_runtime_action"]) == {"base_playbook_only_transition_diagnostic"}
    assert int(frame["playbook_orchestration_routeable"].sum()) == 1
    assert report["summary"]["transition_runtime_enabled_count"] == 0
    assert report["summary"]["recommended_next_step"] == "resume_base_playbook_orchestration_and_shadow_reporting"
    assert "Phase 8A Playbook Orchestration Gate" in md


def test_orchestration_gate_cli_defaults_and_args():
    args = _parse_args(["--asset", "ETHUSDT", "--timeframe", "4h", "--limit", "120"])
    assert args.asset == ["ETHUSDT"]
    assert args.timeframe == "4h"
    assert args.limit == 120

    defaults = _parse_args([])
    assert defaults.asset == ["BNBUSDT", "ETHUSDT", "BTCUSDT"]
    assert defaults.output_json.endswith("phase8a_playbook_orchestration_gate.json")
