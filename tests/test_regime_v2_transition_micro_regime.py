"""Tests for Phase 7T transition micro-regime diagnostics."""

from __future__ import annotations

from libs.models.regime_v2.evaluation.playbook_transition_micro_regime import (
    build_transition_micro_regime_report,
    render_transition_micro_regime_markdown,
)
from libs.models.regime_v2.scripts.report_transition_micro_regime import _parse_args


def _payload():
    return {
        "matrix_report": {
            "variants": [
                {
                    "asset": "ETHUSDT",
                    "timeframe": "1h",
                    "config": {"allowed_market_phases": ["breakout_setup"], "max_volatility_quantile": 0.85, "max_continuation_score": None},
                    "splits": [
                        {"split_index": 1, "split_passed": True, "active_count": 5, "avg_directional_net_return": 0.01, "worst_directional_net_return": 0.001, "direction_distribution": {"up": 3, "down": 2}, "failure_reasons": []},
                        {"split_index": 2, "split_passed": False, "active_count": 2, "avg_directional_net_return": -0.002, "worst_directional_net_return": -0.004, "direction_distribution": {"up": 2}, "failure_reasons": ["low_support", "worst_cell_too_negative"]},
                    ],
                }
            ]
        }
    }


def test_micro_regime_report_and_markdown():
    report = build_transition_micro_regime_report(_payload())
    md = render_transition_micro_regime_markdown(report)

    assert report["phase"] == "phase_7t_transition_micro_regime_diagnostics"
    assert report["summary"]["variant_count"] == 1
    assert report["summary"]["tagged_split_count"] == 2
    assert report["summary"]["recommendation"] == "test_micro_regime_exclusion_next"
    assert "support_thin" in report["summary"]["tag_distribution"]
    assert "# RegimeV2 Phase 7T Transition Micro-Regime Diagnostics" in md


def test_micro_regime_cli_defaults_and_args():
    args = _parse_args(["--input-json", "x.json", "--min-split-active", "4", "--direction-skew-threshold", "0.8"])
    assert args.input_json == "x.json"
    assert args.min_split_active == 4
    assert args.direction_skew_threshold == 0.8

    defaults = _parse_args([])
    assert defaults.input_json == "research/regime_v2_phase7r_transition_setup_prune.json"
    assert defaults.output_json.endswith("phase7t_transition_micro_regime.json")
