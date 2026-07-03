"""Tests for Phase 8D RegimeV2 runtime safety validator."""

from __future__ import annotations

from libs.models.regime_v2.evaluation.runtime_safety_validator import (
    build_runtime_safety_report,
    render_runtime_safety_markdown,
)
from libs.models.regime_v2.scripts.report_8d_safety import _parse_args


def _selection_config(*, trend_enabled: bool = False, paper_enabled: bool = False, invalid_as_valid: bool = False):
    return {
        "selection": {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "overlays": {
                                "regime_v2_trend_gate": {
                                    "enabled": trend_enabled,
                                    "shadow_enabled": True,
                                },
                                "regime_v2_pa_asset_guardrail": {
                                    "paper_enabled": paper_enabled,
                                    "long_horizon_candidate": {
                                        "paper_runtime_enabled": False,
                                        "valid_horizons_bars": [3, 6, 12] if invalid_as_valid else [6, 12, 24],
                                        "invalid_horizons_bars": [] if invalid_as_valid else [3],
                                    },
                                },
                            }
                        }
                    }
                }
            }
        }
    }


def _orchestration():
    return {
        "report": {
            "summary": {
                "transition_runtime_enabled_count": 0,
                "transition_postures": ["frozen_diagnostic"],
            }
        }
    }


def _stop_gate():
    return {"summary": {"decision": "freeze_transition_micro_states_diagnostic", "promotion_ready": False}}


def test_runtime_safety_report_passes_safe_shadow_posture():
    report = build_runtime_safety_report(
        selection_config=_selection_config(),
        orchestration_payload=_orchestration(),
        stop_gate_payload=_stop_gate(),
    )
    md = render_runtime_safety_markdown(report)

    assert report["summary"]["safe"] is True
    assert report["summary"]["runtime_posture"] == "safe_shadow_diagnostic"
    assert report["summary"]["trend_gate_live_enabled_count"] == 0
    assert report["summary"]["transition_runtime_enabled_count"] == 0
    assert report["summary"]["invalid_horizon_issues"] == []
    assert "Phase 8D Runtime Safety Validator" in md


def test_runtime_safety_report_blocks_enabled_runtime_paths():
    report = build_runtime_safety_report(
        selection_config=_selection_config(trend_enabled=True, paper_enabled=True, invalid_as_valid=True),
        orchestration_payload={"report": {"summary": {"transition_runtime_enabled_count": 1, "transition_postures": ["active"]}}},
        stop_gate_payload={"summary": {"decision": "candidate", "promotion_ready": True}},
    )

    blockers = set(report["summary"]["blockers"])
    assert report["summary"]["safe"] is False
    assert "live_trend_gate_enabled" in blockers
    assert "transition_runtime_enabled" in blockers
    assert "transition_posture_not_frozen" in blockers
    assert "transition_stop_gate_promotion_ready" in blockers
    assert "pa_paper_or_runtime_enabled" in blockers
    assert "invalid_horizon_scope_not_preserved" in blockers


def test_runtime_safety_cli_defaults_and_args():
    args = _parse_args(["--selection-config", "s.yaml", "--output-json", "out.json"])
    assert args.selection_config == "s.yaml"
    assert args.output_json == "out.json"

    defaults = _parse_args([])
    assert defaults.selection_config == "configs/selection.yaml"
    assert defaults.output_json.endswith("phase8d_runtime_safety.json")
