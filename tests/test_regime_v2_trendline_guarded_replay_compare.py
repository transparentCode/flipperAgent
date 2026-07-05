from __future__ import annotations

from libs.selection.regime_v2_trendline_guarded_replay_compare import build_guarded_replay_comparison


def _record(asset: str, timeframe: str, lift: float, *, warning: float = 1.0) -> dict:
    return {
        "asset": asset,
        "timeframe": timeframe,
        "selection_changed": True,
        "shadow_minus_baseline": lift,
        "trendline_mid_channel_noise": warning,
        "trendline_no_trade_warning": 0.0,
        "trendline_confidence_annotation": "neutral",
        "trendline_risk_context": "mid_channel_noise",
        "shadow_selected_model": "Momentum",
    }


def test_guarded_replay_comparison_reports_allow_veto_improvement():
    rows = [
        _record("SOLUSDT", "4h", -0.03),
        _record("SOLUSDT", "4h", -0.02),
        _record("ETHUSDT", "4h", 0.05),
    ]

    report = build_guarded_replay_comparison(
        rows,
        allow_asset_timeframes=("SOLUSDT|4h",),
        veto_asset_timeframes=("ETHUSDT|4h",),
    )

    summary = report["summary"]
    assert summary["global_guarded_count"] == 3
    assert summary["allow_veto_guarded_count"] == 2
    assert summary["guarded_count_delta"] == -1
    assert summary["allow_veto_loss_saved_rate"] == 1.0
    assert summary["loss_saved_rate_delta"] > 0.0
    assert summary["allow_veto_missed_good_count"] == 0
    assert summary["missed_good_count_delta"] == -1
    assert summary["net_lift_delta_improvement"] > 0.0
    assert summary["allow_asset_timeframes"] == ["SOLUSDT|4h"]
    assert summary["veto_asset_timeframes"] == ["ETHUSDT|4h"]
