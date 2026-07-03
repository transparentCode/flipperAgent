"""Tests for Phase 7U transition micro-regime separation."""

from __future__ import annotations

from libs.models.regime_v2.evaluation.playbook_transition_micro_separation import (
    build_transition_micro_separation_report,
    render_transition_micro_separation_markdown,
)
from libs.models.regime_v2.scripts.report_transition_micro_separation import _parse_args


def _payload():
    return {
        "matrix_report": {
            "variants": [
                {
                    "asset": "ETHUSDT",
                    "timeframe": "1h",
                    "config": {"allowed_market_phases": ["breakout_setup"]},
                    "post_active_count": 40,
                    "passed_split_count": 3,
                    "split_count": 4,
                    "avg_split_directional_return": 0.005,
                    "worst_split_directional_return": -0.002,
                    "splits": [{"active_count": 10}, {"active_count": 10}, {"active_count": 10}, {"active_count": 10}],
                },
                {
                    "asset": "ETHUSDT",
                    "timeframe": "1h",
                    "config": {"allowed_market_phases": ["compressed_wait"]},
                    "post_active_count": 35,
                    "passed_split_count": 1,
                    "split_count": 4,
                    "avg_split_directional_return": -0.001,
                    "worst_split_directional_return": -0.004,
                    "splits": [{"active_count": 8}, {"active_count": 9}, {"active_count": 8}, {"active_count": 10}],
                },
                {
                    "asset": "BNBUSDT",
                    "timeframe": "1h",
                    "config": {"allowed_market_phases": None},
                    "post_active_count": 50,
                    "passed_split_count": 2,
                    "split_count": 4,
                    "avg_split_directional_return": 0.001,
                    "worst_split_directional_return": -0.003,
                    "splits": [{"active_count": 12}, {"active_count": 12}, {"active_count": 13}, {"active_count": 13}],
                },
            ]
        }
    }


def test_micro_separation_report_and_markdown():
    report = build_transition_micro_separation_report(_payload())
    md = render_transition_micro_separation_markdown(report)

    assert report["phase"] == "phase_7u_transition_micro_separation"
    assert report["summary"]["separation_decision"] == "separate_breakout_setup_from_compressed_wait"
    groups = {row["phase_group"]: row for row in report["groups"]}
    assert groups["breakout_setup"]["recommendation"] == "keep_as_research_candidate"
    assert groups["compressed_wait"]["recommendation"] == "separate_as_observation_only"
    assert "# RegimeV2 Phase 7U Transition Micro-Regime Separation" in md


def test_micro_separation_cli_defaults_and_args():
    args = _parse_args(["--input-json", "x.json", "--min-total-active", "20", "--min-split-active", "2"])
    assert args.input_json == "x.json"
    assert args.min_total_active == 20
    assert args.min_split_active == 2

    defaults = _parse_args([])
    assert defaults.input_json == "research/regime_v2_phase7r_transition_setup_prune.json"
    assert defaults.output_json.endswith("phase7u_transition_micro_separation.json")
