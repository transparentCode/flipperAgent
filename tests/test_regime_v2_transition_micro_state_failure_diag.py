"""Tests for Phase 7X transition micro-state failure diagnostics."""

from __future__ import annotations

from libs.models.regime_v2.evaluation.playbook_transition_micro_state_failure_diag import (
    build_transition_micro_state_failure_diag_report,
    render_transition_micro_state_failure_diag_markdown,
)
from libs.models.regime_v2.scripts.report_transition_micro_state_failure_diag import _parse_args


def _payload():
    return {
        "variant_reports": [
            {
                "summary": {"asset": "BNBUSDT", "timeframe": "1h"},
                "robust_report": {
                    "windows": [
                        {
                            "window_id": "full",
                            "is_full": True,
                            "support_ok": True,
                            "breakout_better": True,
                            "breakout_setup_active": 10,
                            "compression_active": 12,
                            "breakout_setup_avg_return": 0.002,
                            "compression_avg_return": -0.001,
                            "breakout_setup_worst_return": -0.01,
                            "compression_worst_return": -0.03,
                        },
                        {
                            "window_id": "w1",
                            "is_full": False,
                            "support_ok": True,
                            "breakout_better": False,
                            "breakout_setup_active": 8,
                            "compression_active": 9,
                            "breakout_setup_avg_return": -0.002,
                            "compression_avg_return": 0.003,
                            "breakout_setup_worst_return": -0.02,
                            "compression_worst_return": -0.04,
                        },
                        {
                            "window_id": "w2",
                            "is_full": False,
                            "support_ok": False,
                            "breakout_better": True,
                            "breakout_setup_active": 2,
                            "compression_active": 9,
                            "breakout_setup_avg_return": 0.001,
                            "compression_avg_return": -0.001,
                            "breakout_setup_worst_return": -0.01,
                            "compression_worst_return": -0.02,
                        },
                    ]
                },
            }
        ]
    }


def test_failure_diag_report_and_markdown():
    report = build_transition_micro_state_failure_diag_report(_payload(), min_tail_loss=0.02)
    md = render_transition_micro_state_failure_diag_markdown(report)

    assert report["phase"] == "phase_7x_transition_micro_state_failure_diag"
    assert report["summary"]["window_count"] == 3
    assert report["summary"]["supported_failure_count"] == 1
    assert report["summary"]["support_thin_count"] == 1
    assert report["summary"]["recommendation"] == "diagnose_supported_mixed_windows_next"
    assert "state_inversion" in report["summary"]["signature_distribution"]
    assert "# RegimeV2 Phase 7X Transition Micro-State Failure Diagnostics" in md


def test_failure_diag_cli_defaults_and_args():
    args = _parse_args(["--input-json", "x.json", "--min-tail-loss", "0.03"])
    assert args.input_json == "x.json"
    assert args.min_tail_loss == 0.03

    defaults = _parse_args([])
    assert defaults.input_json == "research/regime_v2_phase7w_transition_micro_state_robust.json"
    assert defaults.output_json.endswith("phase7x_transition_micro_state_failure_diag.json")
