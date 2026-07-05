from __future__ import annotations

import numpy as np
import pandas as pd

from libs.trendlines.boundary import TrendlineSnapshotHistory
from libs.models.regime_v2.adapters import (
    TrendlineFeatureConfig,
    TrendlineFeatureProducer,
    compute_trendline_context_features,
)


def _make_frame(n: int = 120, *, datetime_index: bool = True) -> pd.DataFrame:
    x = np.arange(n, dtype=float)
    close = 100.0 + 0.05 * x + np.sin(x / 6.0)
    frame = pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000.0 + x,
        }
    )
    if datetime_index:
        frame.index = pd.date_range("2026-01-01", periods=n, freq="h")
    return frame


def test_trendline_context_features_emit_valid_snapshot():
    features = compute_trendline_context_features(
        _make_frame(),
        asset="btcusdt",
        timeframe="1h",
        config=TrendlineFeatureConfig(fitter="ensemble"),
    )

    assert features["trendline_asset"] == "BTCUSDT"
    assert features["trendline_valid"] == 1.0
    assert features["trendline_error"] is None
    assert features["trendline_support_ray_count"] >= 1.0
    assert features["trendline_resistance_ray_count"] >= 1.0
    assert features["trendline_has_support"] == 1.0
    assert features["trendline_has_resistance"] == 1.0
    assert features["trendline_has_both_sides"] == 1.0
    assert features["trendline_has_closed_channel"] == 1.0
    assert features["trendline_structure_state"] == "closed_channel"
    assert features["trendline_market_position_state"] in {
        "inside_channel",
        "mid_channel_noise",
        "upper_channel_pressure",
        "lower_channel_pressure",
        "near_support",
        "near_resistance",
        "above_channel",
        "below_channel",
    }
    assert features["trendline_inside_channel"] in {0.0, 1.0}
    assert features["trendline_near_support"] in {0.0, 1.0}
    assert features["trendline_near_resistance"] in {0.0, 1.0}
    assert features["trendline_latest_atr"] > 0.0
    assert features["trendline_mean_atr"] > 0.0
    assert features["trendline_hull_width_atr"] > 0.0
    assert 0.0 <= features["trendline_support_quality_score"] <= 1.0
    assert 0.0 <= features["trendline_resistance_quality_score"] <= 1.0
    assert 0.0 <= features["trendline_mean_normalized_quality"] <= 1.0
    assert 0.0 <= features["trendline_hull_position"] <= 1.0
    assert features["trendline_risk_context"] in {
        "valid_structure",
        "mid_channel_noise",
        "near_support_reversal_context",
        "near_resistance_reversal_context",
        "upper_channel_pressure_watch",
        "lower_channel_pressure_watch",
        "above_channel_breakout_context",
        "below_channel_breakdown_context",
        "inside_channel_context",
    }
    assert features["trendline_confidence_annotation"] in {
        "neutral",
        "caution",
        "reversal_watch",
        "breakout_watch",
        "breakdown_watch",
        "continuation_watch",
    }
    assert features["trendline_annotation_reason"]
    assert features["trendline_no_trade_warning"] in {0.0, 1.0}
    assert features["trendline_reversal_context"] in {0.0, 1.0}
    assert features["trendline_breakout_context"] in {0.0, 1.0}
    assert features["trendline_breakdown_context"] in {0.0, 1.0}
    assert features["trendline_breakout_watch_high_quality"] in {0.0, 1.0}
    assert features["trendline_breakout_watch_positive_persistence"] in {0.0, 1.0}
    assert features["trendline_breakout_watch_hull_expansion"] in {0.0, 1.0}
    assert features["trendline_breakout_watch_clean_context"] in {0.0, 1.0}
    assert features["trendline_breakout_watch_confirmed_interaction"] in {0.0, 1.0}
    assert 0.0 <= features["trendline_breakout_watch_strict_score"] <= 5.0
    assert features["trendline_breakout_watch_strict_context"] in {
        "none",
        "breakout_watch_broad",
        "breakout_watch_candidate",
        "breakout_watch_strict",
    }


def test_trendline_context_features_fail_soft_on_short_input():
    features = compute_trendline_context_features(
        _make_frame(10),
        asset="BTCUSDT",
        timeframe="1h",
    )

    assert features["trendline_valid"] == 0.0
    assert features["trendline_error"].startswith("insufficient_bars")
    assert features["trendline_risk_context"] == "invalid_or_missing"
    assert features["trendline_confidence_annotation"] == "neutral"
    assert features["trendline_annotation_reason"] == "no_valid_trendline_context"
    assert features["trendline_breakout_watch_strict_context"] == "none"
    assert features["trendline_breakout_watch_strict_score"] == 0.0


def test_trendline_context_features_can_opt_into_pathfinding_refit_mode():
    features = compute_trendline_context_features(
        _make_frame(),
        asset="BTCUSDT",
        timeframe="1h",
        config=TrendlineFeatureConfig(
            fitter="ensemble",
            pathfinding_line_fit_mode="ols_on_path",
        ),
    )

    assert features["trendline_valid"] == 1.0
    assert features["trendline_has_closed_channel"] == 1.0


def test_trendline_context_features_records_and_reads_snapshot_history():
    snapshot_history = TrendlineSnapshotHistory(maxlen=5)
    config = TrendlineFeatureConfig(
        fitter="ensemble",
        min_bars=30,
        include_native_signals=True,
        record_snapshot=True,
        history_limit=3,
    )

    first = compute_trendline_context_features(
        _make_frame(80),
        asset="BTCUSDT",
        timeframe="1h",
        config=config,
        snapshot_history=snapshot_history,
    )
    second = compute_trendline_context_features(
        _make_frame(100),
        asset="BTCUSDT",
        timeframe="1h",
        config=config,
        snapshot_history=snapshot_history,
    )

    assert first["trendline_valid"] == 1.0
    assert first["trendline_history_count"] == 0.0
    assert first["trendline_snapshot_recorded"] == 1.0
    assert second["trendline_valid"] == 1.0
    assert second["trendline_history_count"] == 1.0
    assert second["trendline_snapshot_recorded"] == 1.0
    assert second["trendline_prev_interaction"] in {
        "NONE",
        "GEOMETRIC_BOUNCE_SUPPORT",
        "GEOMETRIC_BOUNCE_RESISTANCE",
        "STRUCTURAL_BREAKOUT",
        "STRUCTURAL_BREAKDOWN",
    }
    assert "->" in second["trendline_interaction_transition"]
    assert "->" in second["trendline_market_position_transition"]
    assert isinstance(second["trendline_hull_width_delta"], float)
    assert isinstance(second["trendline_hull_convergence_rate"], float)
    assert isinstance(second["trendline_hull_expansion_rate"], float)
    assert 0.0 <= second["trendline_support_persistence"] <= 1.0
    assert 0.0 <= second["trendline_resistance_persistence"] <= 1.0
    assert -1.0 <= second["trendline_ray_persistence_bias"] <= 1.0
    assert isinstance(second["trendline_slope_acceleration"], float)
    assert snapshot_history.count("BTCUSDT", "1h") == 2


def test_trendline_temporal_fields_are_neutral_without_snapshot_history():
    features = compute_trendline_context_features(
        _make_frame(80),
        asset="BTCUSDT",
        timeframe="1h",
        config=TrendlineFeatureConfig(fitter="ensemble", min_bars=30),
    )

    assert features["trendline_valid"] == 1.0
    assert features["trendline_history_count"] == 0.0
    assert features["trendline_prev_interaction"] == "NONE"
    assert features["trendline_interaction_transition"] == "NONE->NONE"
    assert features["trendline_market_position_transition"] == "unknown->unknown"
    assert features["trendline_hull_width_delta"] == 0.0
    assert features["trendline_support_persistence"] == 0.0
    assert features["trendline_ray_persistence_bias"] == 0.0
    assert features["trendline_risk_context"] != "invalid_or_missing"
    assert features["trendline_confidence_annotation"] != "neutral" or features["trendline_annotation_reason"] != "no_valid_trendline_context"


def test_trendline_feature_producer_accepts_plain_price_history():
    producer = TrendlineFeatureProducer(
        "BTCUSDT",
        "1h",
        config=TrendlineFeatureConfig(fitter="ensemble", min_bars=30),
    )

    features = producer.analyze(_make_frame(datetime_index=False).to_dict("records"))

    assert features["trendline_valid"] == 1.0
    assert features["trendline_interaction"] in {
        "NONE",
        "GEOMETRIC_BOUNCE_SUPPORT",
        "GEOMETRIC_BOUNCE_RESISTANCE",
        "STRUCTURAL_BREAKOUT",
        "STRUCTURAL_BREAKDOWN",
    }
