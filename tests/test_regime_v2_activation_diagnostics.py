"""Tests for RegimeV2 activation diagnostics."""

from __future__ import annotations

from libs.models.regime_v2.scripts.diagnose_shadow_activation import _parse_args
from libs.selection.regime_v2_activation_diagnostics import (
    build_regime_v2_activation_diagnostics,
    render_regime_v2_activation_diagnostics_markdown,
)


def _record(
    *,
    asset: str = "BTCUSDT",
    timeframe: str = "4h",
    active: bool = False,
    changed: bool = False,
    active_playbooks: list[str] | None = None,
    target_candidate_count: int = 1,
    allow_trend: bool = False,
    trend_score: float = 0.1,
    allow_breakout: bool = False,
    breakout_score: float = 0.1,
    allow_mr: bool = False,
    mr_score: float = 0.1,
    confidence: float = 0.8,
) -> dict:
    return {
        "asset": asset,
        "timeframe": timeframe,
        "gate_active": active,
        "selection_changed": changed,
        "gate_reason": "active" if active else "inactive_playbook_policy",
        "active_playbooks": active_playbooks or ([] if not active else ["trend"]),
        "baseline_selected_model": "Momentum",
        "shadow_selected_model": "Momentum" if not changed else "SqueezeBreakout",
        "target_candidate_count": target_candidate_count,
        "allow_trend_following": allow_trend,
        "allow_breakout": allow_breakout,
        "allow_mean_reversion": allow_mr,
        "trend_score": trend_score,
        "breakout_score": breakout_score,
        "mean_reversion_score": mr_score,
        "min_trend_score": 0.24,
        "min_breakout_score": 0.24,
        "min_mean_reversion_score": 0.24,
        "min_confidence": 0.0,
        "confidence": confidence,
    }


def test_activation_diagnostics_counts_active_inactive_and_blockers():
    records = [
        _record(active=True, changed=True, active_playbooks=["trend"], allow_trend=True, trend_score=0.4),
        _record(active=False, changed=False, target_candidate_count=0, allow_trend=False, trend_score=0.3),
        _record(active=False, changed=True, allow_trend=True, trend_score=0.1, allow_breakout=True, breakout_score=0.3),
    ]

    report = build_regime_v2_activation_diagnostics(records, relaxed_floors=(0.18, 0.24))
    summary = report["summary"]

    assert summary["total_records"] == 3
    assert summary["gate_active_count"] == 1
    assert summary["gate_active_rate"] == 1 / 3
    assert summary["gate_active_changed_count"] == 1
    assert summary["target_candidate_absent_count"] == 1
    assert report["playbooks"]["trend"]["allow_true_count"] == 2
    assert report["playbooks"]["trend"]["score_pass_count"] == 2
    assert report["playbooks"]["breakout"]["allow_and_score_pass_count"] == 1
    blockers = {row["blocker"]: row["count"] for row in report["top_blockers"]}
    assert blockers["no_target_candidate"] == 1
    assert blockers["trend_allow_false"] == 1
    assert blockers["trend_score_below_floor"] == 1


def test_activation_diagnostics_relaxed_floor_scenarios():
    records = [
        _record(allow_trend=True, trend_score=0.19),
        _record(allow_trend=True, trend_score=0.23),
        _record(allow_trend=True, trend_score=0.25),
    ]

    report = build_regime_v2_activation_diagnostics(records, relaxed_floors=(0.18, 0.22, 0.24))

    scenarios = {row["floor"]: row for row in report["relaxed_floor_scenarios"]}
    assert scenarios[0.18]["potential_active_count"] == 3
    assert scenarios[0.18]["score_only_potential_active_count"] == 3
    assert scenarios[0.22]["potential_active_count"] == 2
    assert scenarios[0.22]["score_only_potential_active_count"] == 2
    assert scenarios[0.24]["potential_active_count"] == 1
    assert scenarios[0.24]["score_only_potential_active_count"] == 1


def test_activation_diagnostics_pair_summary_and_markdown():
    report = build_regime_v2_activation_diagnostics(
        [
            _record(asset="BTCUSDT", timeframe="4h", active=True, active_playbooks=["breakout"], allow_breakout=True, breakout_score=0.5),
            _record(asset="ETHUSDT", timeframe="4h", active=False, allow_trend=False, trend_score=0.1),
        ]
    )

    assert report["asset_timeframe"]["BTCUSDT|4h"]["gate_active_count"] == 1
    assert report["asset_timeframe"]["ETHUSDT|4h"]["gate_active_count"] == 0
    md = render_regime_v2_activation_diagnostics_markdown(report)
    assert "# RegimeV2 Phase 6C Activation Diagnostics" in md
    assert "| trend |" in md
    assert "## Relaxed Floor Scenarios" in md


def test_diagnose_shadow_activation_cli_parse_args():
    args = _parse_args(
        [
            "--log",
            "logs/custom.jsonl",
            "--relaxed-floor",
            "0.2",
            "--relaxed-floor",
            "0.24",
            "--output-json",
            "research/diag.json",
            "--output-md",
            "research/diag.md",
        ]
    )

    assert args.log == "logs/custom.jsonl"
    assert args.relaxed_floor == [0.2, 0.24]
    assert args.output_json == "research/diag.json"
    assert args.output_md == "research/diag.md"


def test_diagnose_shadow_activation_cli_defaults():
    args = _parse_args([])

    assert args.relaxed_floor == [0.18, 0.20, 0.22, 0.24]
    assert args.output_json == "research/regime_v2_activation_diagnostics.json"
    assert args.output_md == "research/regime_v2_activation_diagnostics.md"
