from __future__ import annotations

import pytest

from libs.selection.regime_v2_trendline_guarded_replay import (
    GuardedReplayConfig,
    build_trendline_guarded_replay,
    render_trendline_guarded_replay_markdown,
)


def _record(
    *,
    changed: bool = True,
    lift: float = -0.01,
    mid_noise: float = 1.0,
    no_trade: float = 0.0,
    annotation: str = "neutral",
    risk: str = "mid_channel_noise",
    asset: str = "BTCUSDT",
    timeframe: str = "4h",
    model: str = "Momentum",
) -> dict:
    return {
        "asset": asset,
        "timeframe": timeframe,
        "selection_changed": changed,
        "shadow_minus_baseline": lift,
        "trendline_mid_channel_noise": mid_noise,
        "trendline_no_trade_warning": no_trade,
        "trendline_confidence_annotation": annotation,
        "trendline_risk_context": risk,
        "shadow_selected_model": model,
        "outcome_label": "missed_win" if lift < 0 else "avoided_loss",
    }


def test_guarded_replay_falls_back_to_baseline_for_warning_changed_rows():
    rows = [
        _record(lift=-0.03),
        _record(lift=-0.02),
        _record(lift=0.01),
        _record(lift=0.04, mid_noise=0.0, changed=True),
        _record(lift=-0.05, mid_noise=1.0, changed=False),
    ]

    report = build_trendline_guarded_replay(
        rows,
        config=GuardedReplayConfig(
            warning_basket=(("trendline_mid_channel_noise", 1.0),),
            min_guarded_samples=3,
            min_loss_saved_rate=0.6,
        ),
    )

    summary = report["summary"]
    assert summary["labeled_count"] == 5
    assert summary["changed_labeled_count"] == 4
    assert summary["guarded_count"] == 3
    assert summary["loss_saved_count"] == 2
    assert summary["missed_good_count"] == 1
    assert summary["loss_saved_rate"] == 2 / 3
    assert summary["loss_saved_total"] == pytest.approx(0.05)
    assert summary["missed_good_total"] == pytest.approx(0.01)
    assert summary["net_lift_delta"] == pytest.approx(0.04 / 5)
    assert summary["replay_status"] == "candidate_ready"


def test_guarded_replay_rejects_basket_that_blocks_good_lift():
    rows = [
        _record(lift=0.03, no_trade=1.0, mid_noise=0.0),
        _record(lift=0.02, no_trade=1.0, mid_noise=0.0),
        _record(lift=-0.01, no_trade=1.0, mid_noise=0.0),
    ]

    report = build_trendline_guarded_replay(
        rows,
        config=GuardedReplayConfig(
            warning_basket=(("trendline_no_trade_warning", 1.0),),
            min_guarded_samples=3,
            min_loss_saved_rate=0.6,
        ),
    )

    summary = report["summary"]
    assert summary["guarded_count"] == 3
    assert summary["loss_saved_rate"] == 1 / 3
    assert summary["net_lift_delta"] < 0.0
    assert summary["replay_status"] == "needs_more_evidence"


def test_guarded_replay_respects_asset_timeframe_allowlist_and_veto():
    rows = [
        _record(asset="SOLUSDT", timeframe="4h", lift=-0.03),
        _record(asset="ETHUSDT", timeframe="4h", lift=-0.04),
        _record(asset="BTCUSDT", timeframe="1h", lift=-0.05),
    ]

    report = build_trendline_guarded_replay(
        rows,
        config=GuardedReplayConfig(
            allowed_asset_timeframes=("SOLUSDT|4h", "ETHUSDT|4h"),
            veto_asset_timeframes=("ETHUSDT|4h",),
            min_guarded_samples=1,
            min_loss_saved_rate=0.5,
        ),
    )

    summary = report["summary"]
    assert summary["allowed_asset_timeframes"] == ["SOLUSDT|4h", "ETHUSDT|4h"]
    assert summary["veto_asset_timeframes"] == ["ETHUSDT|4h"]
    assert summary["guarded_count"] == 1
    assert report["guarded_rows"]["asset_timeframe"] == {"SOLUSDT|4h": 1}
    assert summary["loss_saved_total"] == 0.03


def test_guarded_replay_groups_by_asset_model_and_context():
    rows = [
        _record(asset="BTCUSDT", timeframe="4h", model="Momentum", lift=-0.02),
        _record(asset="ETHUSDT", timeframe="1h", model="TrendFollowing", lift=0.01, annotation="reversal_watch", mid_noise=0.0),
        _record(asset="ETHUSDT", timeframe="1h", model="TrendFollowing", lift=-0.03, annotation="reversal_watch", mid_noise=0.0),
    ]

    report = build_trendline_guarded_replay(
        rows,
        config=GuardedReplayConfig(min_guarded_samples=1, min_loss_saved_rate=0.0),
    )

    assert report["guarded_rows"]["asset_timeframe"] == {"BTCUSDT|4h": 1, "ETHUSDT|1h": 2}
    assert report["guarded_rows"]["shadow_model"] == {"Momentum": 1, "TrendFollowing": 2}
    assert any(row["group"] == "BTCUSDT|4h" for row in report["grouped"]["asset_timeframe"])
    assert any(row["group"] == "TrendFollowing" for row in report["grouped"]["shadow_model"])


def test_guarded_replay_filters_asset_timeframe_and_renders_markdown():
    rows = [
        _record(asset="BTCUSDT", timeframe="4h", lift=-0.02),
        _record(asset="ETHUSDT", timeframe="1h", lift=-0.02),
    ]

    report = build_trendline_guarded_replay(
        rows,
        asset="btcusdt",
        timeframe="4h",
        config=GuardedReplayConfig(min_guarded_samples=1, min_loss_saved_rate=0.5),
    )
    md = render_trendline_guarded_replay_markdown(report)

    assert report["summary"]["records_after_filter"] == 1
    assert report["summary"]["asset_filter"] == "BTCUSDT"
    assert "# RegimeV2 Trendline Guarded Replay" in md
    assert "Grouped Impact" in md
