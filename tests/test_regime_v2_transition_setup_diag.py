"""Tests for Phase 7Q setup-transition diagnostics."""

from __future__ import annotations

from libs.models.regime_v2.evaluation.playbook_transition_setup_diag import (
    build_setup_transition_diag_report,
    render_setup_transition_diag_markdown,
)
from libs.models.regime_v2.scripts.report_transition_setup_diag import _parse_args


def _matrix_payload():
    return {
        "matrix_report": {
            "variants": [
                {
                    "asset": "ETHUSDT",
                    "timeframe": "1h",
                    "active_count": 61,
                    "passed_split_count": 3,
                    "split_count": 4,
                    "avg_split_directional_return": 0.004,
                    "worst_split_directional_return": -0.003,
                    "ready": False,
                    "direction_distribution": {"down": 31, "up": 30},
                    "state_distribution": {"FAILED_BREAKOUT_REVERSAL_SETUP": 61},
                    "config": {"lookback_bars": 8, "min_candidate_score": 0.62},
                    "splits": [
                        {"split_index": 1, "split_passed": True, "active_count": 20, "failure_reasons": [], "direction_distribution": {"down": 10, "up": 10}, "passing_cell_rate": 1.0, "avg_directional_net_return": 0.01, "worst_directional_net_return": 0.001},
                        {"split_index": 2, "split_passed": False, "active_count": 15, "failure_reasons": ["worst_cell_too_negative"], "direction_distribution": {"down": 13, "up": 2}, "passing_cell_rate": 0.4, "avg_directional_net_return": -0.002, "worst_directional_net_return": -0.006},
                    ],
                },
                {
                    "asset": "BNBUSDT",
                    "timeframe": "1h",
                    "active_count": 40,
                    "passed_split_count": 2,
                    "split_count": 4,
                    "avg_split_directional_return": 0.001,
                    "worst_split_directional_return": -0.005,
                    "ready": False,
                    "config": {"lookback_bars": 20, "min_candidate_score": 0.66},
                    "splits": [],
                },
            ]
        }
    }


def test_setup_transition_diag_report_and_markdown():
    report = build_setup_transition_diag_report(_matrix_payload())
    md = render_setup_transition_diag_markdown(report)

    assert report["phase"] == "phase_7q_setup_transition_diagnostics"
    assert report["summary"]["best_variant"]["asset"] == "ETHUSDT"
    assert report["summary"]["best_failure_profile"]["failed_split_count"] == 1
    assert report["summary"]["recommendation"] == "diagnose_worst_cell_prune_before_promotion"
    assert "# RegimeV2 Phase 7Q Setup Transition Diagnostics" in md


def test_setup_transition_diag_cli_args():
    args = _parse_args(["--input-json", "x.json", "--min-active-support", "50", "--min-passed-splits", "3"])
    assert args.input_json == "x.json"
    assert args.min_active_support == 50
    assert args.min_passed_splits == 3

    defaults = _parse_args([])
    assert defaults.input_json == "research/regime_v2_phase7p_transition_setup.json"
    assert defaults.output_json.endswith("phase7q_transition_setup_diag.json")
