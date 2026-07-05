from __future__ import annotations

from libs.selection.regime_v2_trendline_guarded_replay_groups import (
    GuardedGroupThresholds,
    build_guarded_replay_group_analysis,
    render_guarded_replay_group_analysis_markdown,
)


def _group(name: str, guarded: int, loss_rate: float | None, delta: float) -> dict:
    return {
        "group": name,
        "row_count": 100,
        "guarded_count": guarded,
        "loss_saved_rate": loss_rate,
        "net_lift_delta": delta,
    }


def test_group_analysis_classifies_allow_veto_and_needs_more_evidence():
    replay = {
        "grouped": {
            "asset_timeframe": [
                _group("SOLUSDT|4h", 10, 0.70, 0.001),
                _group("ETHUSDT|4h", 9, 0.44, -0.001),
                _group("BTCUSDT|1h", 2, 1.0, 0.002),
            ],
            "shadow_model": [],
            "risk_context": [],
            "confidence_annotation": [],
        }
    }

    report = build_guarded_replay_group_analysis(
        replay,
        thresholds=GuardedGroupThresholds(min_guarded_samples=5),
    )

    decisions = {row["group"]: row["group_decision"] for row in report["asset_timeframe"]}
    assert decisions["SOLUSDT|4h"] == "allow_candidate"
    assert decisions["ETHUSDT|4h"] == "veto_candidate"
    assert decisions["BTCUSDT|1h"] == "needs_more_evidence"
    assert report["summary"]["allow_candidate_count"] == 1
    assert report["summary"]["veto_candidate_count"] == 1
    assert report["summary"]["needs_more_evidence_count"] == 1


def test_group_analysis_markdown_contains_decisions():
    replay = {"grouped": {"asset_timeframe": [_group("SOLUSDT|4h", 10, 0.7, 0.001)]}}

    report = build_guarded_replay_group_analysis(replay)
    md = render_guarded_replay_group_analysis_markdown(report)

    assert "# RegimeV2 Trendline Guarded Replay Group Analysis" in md
    assert "SOLUSDT|4h" in md
    assert "allow_candidate" in md
