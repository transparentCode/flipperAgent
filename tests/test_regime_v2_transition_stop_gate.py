"""Tests for Phase 7Z transition stop-gate."""

from __future__ import annotations

from libs.models.regime_v2.evaluation.playbook_transition_stop_gate import (
    build_transition_stop_gate_report,
    render_transition_stop_gate_markdown,
)
from libs.models.regime_v2.scripts.report_transition_stop_gate import _parse_args


def _robust_payload():
    return {
        "matrix_report": {
            "summary": {
                "runtime_enabled_count": 0,
                "support_ready_asset_count": 1,
                "supported_window_count": 4,
                "supported_breakout_better_count": 3,
            },
            "variants": [
                {
                    "asset": "ETHUSDT",
                    "support_ready": True,
                    "recommendation": "micro_state_split_window_supported",
                    "supported_window_count": 3,
                    "supported_breakout_better_count": 3,
                },
                {
                    "asset": "BNBUSDT",
                    "support_ready": False,
                    "recommendation": "micro_state_split_window_mixed",
                    "supported_window_count": 4,
                    "supported_breakout_better_count": 2,
                },
            ],
        }
    }


def _context_payload():
    return {
        "matrix_report": {
            "summary": {"candidate_tag_count": 0, "mixed_window_count": 2},
            "variants": [
                {"asset": "ETHUSDT", "mixed_window_count": 0, "candidate_tag_count": 0},
                {"asset": "BNBUSDT", "mixed_window_count": 2, "candidate_tag_count": 0},
            ],
        }
    }


def test_stop_gate_blocks_transition_promotion_and_renders_markdown():
    report = build_transition_stop_gate_report(_robust_payload(), _context_payload())
    md = render_transition_stop_gate_markdown(report)

    assert report["phase"] == "phase_7z_transition_stop_gate"
    assert report["summary"]["promotion_ready"] is False
    assert report["summary"]["decision"] == "freeze_transition_micro_states_diagnostic"
    assert "insufficient_support_ready_assets" in report["summary"]["blockers"]
    assert "no_policy_safe_context_tag_for_mixed_failures" in report["summary"]["blockers"]
    assert "# RegimeV2 Phase 7Z Transition Stop-Gate" in md


def test_stop_gate_cli_defaults_and_args():
    args = _parse_args(["--robust-json", "r.json", "--context-json", "c.json", "--min-support-ready-assets", "3"])
    assert args.robust_json == "r.json"
    assert args.context_json == "c.json"
    assert args.min_support_ready_assets == 3

    defaults = _parse_args([])
    assert defaults.robust_json == "research/regime_v2_phase7w_transition_micro_state_robust.json"
    assert defaults.output_json.endswith("phase7z_transition_stop_gate.json")
