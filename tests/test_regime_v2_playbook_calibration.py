"""Tests for RegimeV2 playbook threshold calibration."""

from __future__ import annotations

from libs.models.regime_v2.scripts.calibrate_playbook_thresholds import _parse_args
from libs.selection.regime_v2_playbook_calibration import (
    build_regime_v2_playbook_calibration,
    render_regime_v2_playbook_calibration_markdown,
)


def _record(
    *,
    baseline_model: str = "Momentum",
    shadow_model: str | None = "Momentum",
    changed: bool = False,
    subset_only: bool = False,
    allow_trend: bool = False,
    trend_score: float = 0.0,
    allow_breakout: bool = False,
    breakout_score: float = 0.0,
    allow_mr: bool = False,
    mr_score: float = 0.0,
    lift: float = 0.0,
    label: str = "unchanged",
    active_playbooks: list[str] | None = None,
) -> dict:
    return {
        "outcome_label": label,
        "baseline_selected_model": baseline_model,
        "shadow_selected_model": shadow_model,
        "selection_changed": changed,
        "subset_only_changed": subset_only,
        "baseline_net_return": 0.0,
        "shadow_net_return": lift,
        "shadow_minus_baseline": lift,
        "allow_trend_following": allow_trend,
        "trend_score": trend_score,
        "allow_breakout": allow_breakout,
        "breakout_score": breakout_score,
        "allow_mean_reversion": allow_mr,
        "mean_reversion_score": mr_score,
        "active_playbooks": active_playbooks or [],
    }


def test_playbook_calibration_splits_policy_score_and_allow_blocked_rows():
    records = [
        _record(allow_trend=True, trend_score=0.25, lift=0.02, active_playbooks=["trend"]),
        _record(allow_trend=False, trend_score=0.25, lift=0.03),
        _record(allow_trend=True, trend_score=0.12, lift=-0.01),
    ]

    report = build_regime_v2_playbook_calibration(records, floors=(0.10, 0.20))
    trend_rows = {row["floor"]: row for row in report["playbooks"]["trend"]["floor_sweep"]}

    assert trend_rows[0.20]["policy_gated"]["count"] == 1
    assert trend_rows[0.20]["policy_gated"]["avg_shadow_minus_baseline"] == 0.02
    assert trend_rows[0.20]["score_only"]["count"] == 2
    assert trend_rows[0.20]["allow_blocked_score_pass"]["count"] == 1
    assert trend_rows[0.10]["policy_gated"]["count"] == 2
    assert report["summary"]["best_policy_gated_cell"]["playbook"] == "trend"
    assert report["summary"]["best_score_only_cell"]["playbook"] == "trend"


def test_playbook_calibration_price_action_report():
    report = build_regime_v2_playbook_calibration(
        [
            _record(baseline_model="PriceAction", shadow_model=None, changed=True, subset_only=True, lift=0.03, label="avoided_loss"),
            _record(baseline_model="PriceAction", shadow_model=None, changed=True, subset_only=True, lift=-0.02, label="missed_win"),
            _record(baseline_model="Momentum", shadow_model="Momentum", lift=0.0),
        ],
        floors=(0.20,),
    )

    price_action = report["price_action"]
    assert price_action["count"] == 2
    assert round(price_action["avg_shadow_minus_baseline"], 6) == 0.005
    assert price_action["positive_shadow_lift_rate"] == 0.5
    assert price_action["outcome_labels"] == {"avoided_loss": 1, "missed_win": 1}


def test_playbook_calibration_ignores_unlabeled_rows():
    report = build_regime_v2_playbook_calibration(
        [
            _record(allow_trend=True, trend_score=0.25, lift=0.02),
            {"outcome_label": "unlabeled", "trend_score": 0.5, "allow_trend_following": True},
        ],
        floors=(0.20,),
    )

    assert report["summary"]["total_records"] == 2
    assert report["summary"]["labeled_count"] == 1
    assert report["summary"]["unlabeled_count"] == 1
    assert report["playbooks"]["trend"]["floor_sweep"][0]["policy_gated"]["count"] == 1


def test_render_playbook_calibration_markdown_contains_sections():
    report = build_regime_v2_playbook_calibration(
        [_record(allow_trend=True, trend_score=0.25, lift=0.02)],
        floors=(0.20,),
    )

    md = render_regime_v2_playbook_calibration_markdown(report)

    assert "# RegimeV2 Phase 6D Playbook Calibration" in md
    assert "## Playbook Floor Sweep" in md
    assert "## PriceAction Subset Removal" in md
    assert "| trend | 0.2 |" in md


def test_calibrate_playbook_thresholds_cli_parse_args():
    args = _parse_args(
        [
            "--outcomes",
            "research/custom.jsonl",
            "--floor",
            "0.12",
            "--floor",
            "0.24",
            "--output-json",
            "research/calibration.json",
            "--output-md",
            "research/calibration.md",
        ]
    )

    assert args.outcomes == "research/custom.jsonl"
    assert args.floor == [0.12, 0.24]
    assert args.output_json == "research/calibration.json"
    assert args.output_md == "research/calibration.md"


def test_calibrate_playbook_thresholds_cli_defaults():
    args = _parse_args([])

    assert args.outcomes == "research/regime_v2_shadow_outcomes.jsonl"
    assert args.floor == [0.10, 0.14, 0.18, 0.20, 0.22, 0.24]
