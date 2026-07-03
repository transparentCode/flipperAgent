"""Tests for Phase 7S support-aware transition validation."""

from __future__ import annotations

from libs.models.regime_v2.evaluation.playbook_transition_support_validation import (
    build_transition_support_validation_report,
    render_transition_support_validation_markdown,
)
from libs.models.regime_v2.scripts.report_transition_support_validation import _parse_args


def _payload():
    return {
        "matrix_report": {
            "variants": [
                {
                    "asset": "ETHUSDT",
                    "timeframe": "1h",
                    "post_active_count": 15,
                    "passed_split_count": 3,
                    "split_count": 4,
                    "avg_split_directional_return": 0.007,
                    "worst_split_directional_return": -0.0019,
                    "config": {"phase": "unit"},
                    "splits": [
                        {"split_index": 1, "active_count": 4},
                        {"split_index": 2, "active_count": 6},
                        {"split_index": 3, "active_count": 2},
                        {"split_index": 4, "active_count": 3},
                    ],
                },
                {
                    "asset": "BNBUSDT",
                    "timeframe": "1h",
                    "post_active_count": 35,
                    "passed_split_count": 4,
                    "split_count": 4,
                    "avg_split_directional_return": 0.002,
                    "worst_split_directional_return": -0.0005,
                    "config": {"phase": "ready"},
                    "splits": [
                        {"split_index": 1, "active_count": 8},
                        {"split_index": 2, "active_count": 9},
                        {"split_index": 3, "active_count": 8},
                        {"split_index": 4, "active_count": 10},
                    ],
                },
            ]
        }
    }


def test_support_validation_scores_and_markdown():
    report = build_transition_support_validation_report(_payload())
    md = render_transition_support_validation_markdown(report)

    assert report["phase"] == "phase_7s_transition_support_validation"
    assert report["summary"]["support_ready_count"] == 1
    assert report["summary"]["best_ready_variant"]["asset"] == "BNBUSDT"
    assert report["summary"]["grade_distribution"]["support_ready"] == 1
    assert "# RegimeV2 Phase 7S Transition Support Validation" in md


def test_support_validation_can_mark_promising_thin():
    report = build_transition_support_validation_report(_payload(), min_total_active=30, min_split_active=3, max_worst_loss=0.003)
    eth = [row for row in report["variants"] if row["asset"] == "ETHUSDT"][0]

    assert eth["support_grade"] == "promising_thin"
    assert "total_support_low" in eth["support_blockers"]
    assert "split_support_low" in eth["support_blockers"]


def test_support_validation_cli_defaults_and_args():
    args = _parse_args(["--input-json", "x.json", "--min-total-active", "20", "--min-split-active", "2"])
    assert args.input_json == "x.json"
    assert args.min_total_active == 20
    assert args.min_split_active == 2

    defaults = _parse_args([])
    assert defaults.input_json == "research/regime_v2_phase7r_transition_setup_prune.json"
    assert defaults.output_json.endswith("phase7s_transition_support_validation.json")
