from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from libs.models.trendlines.boundary import TrendlineSnapshotHistory
from libs.models.trendlines.config import SnapshotHistoryPolicies, SnapshotHistoryPolicy
from libs.models.trendlines import fit_trendlines_to_boundary
from libs.models.regime_v2.adapters import (
    TrendlineFeatureConfig,
    TrendlineFeatureProducer,
    compute_trendline_context_features,
)
from libs.models.regime_v2.adapters.trendline_feature_producer import (
    _resolve_bar_availability,
    _signal_history,
)
from libs.models.trendlines.signals.context import BarTimestampSemantics


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
    snapshot_history = TrendlineSnapshotHistory(
        SnapshotHistoryPolicies(SnapshotHistoryPolicy(5, 8, 3), {})
    )
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


def test_regime_v2_records_snapshot_known_at_using_bar_availability():
    snapshot_history = TrendlineSnapshotHistory(
        SnapshotHistoryPolicies(SnapshotHistoryPolicy(10, 8, 3), {})
    )
    frame = _make_frame(80)

    features = compute_trendline_context_features(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        config=TrendlineFeatureConfig(
            fitter="ensemble",
            min_bars=30,
            record_snapshot=True,
        ),
        snapshot_history=snapshot_history,
    )

    assert features["trendline_valid"] == 1.0
    snapshot = snapshot_history.snapshots("BTCUSDT", "1h")[0]
    expected = pd.Timestamp(frame.index[-1], tz="UTC") + pd.Timedelta(hours=1)
    assert snapshot.known_at == expected.to_pydatetime()
    assert snapshot.known_at != pd.Timestamp(frame.index[-1], tz="UTC").to_pydatetime()


def test_regime_v2_native_signals_exclude_revision_unknown_at_bar_availability(
    monkeypatch,
):
    from libs.models.regime_v2.adapters import trendline_feature_producer as producer_module

    historical_frame = _make_frame(80)
    revised_frame = historical_frame.copy()
    revised_frame.iloc[10, revised_frame.columns.get_loc("close")] += 0.25
    current_frame = _make_frame(100)

    original = fit_trendlines_to_boundary(
        historical_frame,
        asset="BTCUSDT",
        timeframe="1h",
        fitter="ensemble",
    ).boundary_result
    revised = fit_trendlines_to_boundary(
        revised_frame,
        asset="BTCUSDT",
        timeframe="1h",
        fitter="ensemble",
    ).boundary_result
    assert original is not None
    assert revised is not None
    assert original.snapshot_identity is not None
    assert revised.snapshot_identity is not None
    assert original.snapshot_identity.snapshot_id == revised.snapshot_identity.snapshot_id
    assert original.snapshot_identity.revision_id != revised.snapshot_identity.revision_id

    history = TrendlineSnapshotHistory(
        SnapshotHistoryPolicies(SnapshotHistoryPolicy(10, 8, 3), {})
    )
    event = pd.Timestamp(historical_frame.index[-1], tz="UTC")
    history.add(original, known_at=(event + pd.Timedelta(minutes=30)).to_pydatetime())
    history.add(
        revised,
        known_at=(pd.Timestamp(current_frame.index[-1], tz="UTC") + pd.Timedelta(hours=2)).to_pydatetime(),
    )

    captured: dict[str, object] = {}

    def fake_fit_and_signal(frame, *, signal_inputs, **kwargs):
        captured["signal_inputs"] = signal_inputs
        return fit_trendlines_to_boundary(
            frame,
            asset=kwargs["asset"],
            timeframe=kwargs["timeframe"],
            extractor=kwargs["extractor"],
            fitter=kwargs["fitter"],
            fitter_kwargs=kwargs.get("fitter_kwargs"),
        )

    monkeypatch.setattr(producer_module, "fit_and_signal", fake_fit_and_signal)
    features = compute_trendline_context_features(
        current_frame,
        asset="BTCUSDT",
        timeframe="1h",
        config=TrendlineFeatureConfig(
            fitter="ensemble",
            min_bars=30,
            include_native_signals=True,
        ),
        snapshot_history=history,
    )

    assert features["trendline_valid"] == 1.0
    signal_inputs = captured["signal_inputs"]
    assert len(signal_inputs.history) == 1
    assert (
        signal_inputs.history[0].snapshot_identity.revision_id
        == original.snapshot_identity.revision_id
    )


def _history_for_limit_tests() -> TrendlineSnapshotHistory:
    history = TrendlineSnapshotHistory(
        SnapshotHistoryPolicies(SnapshotHistoryPolicy(10, 8, 2), {})
    )
    config = TrendlineFeatureConfig(
        fitter="ensemble",
        min_bars=30,
        record_snapshot=True,
    )
    for size in (80, 100):
        features = compute_trendline_context_features(
            _make_frame(size),
            asset="BTCUSDT",
            timeframe="1h",
            config=config,
            snapshot_history=history,
        )
        assert features["trendline_valid"] == 1.0
    return history


def test_history_limit_none_uses_history_policy_context_limit():
    history = _history_for_limit_tests()

    selected = _signal_history(
        history,
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=pd.Timestamp("2026-01-10", tz="UTC"),
        limit=None,
    )

    assert len(selected) == 2


def test_positive_history_limit_overrides_query_length():
    history = _history_for_limit_tests()

    selected = _signal_history(
        history,
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=pd.Timestamp("2026-01-10", tz="UTC"),
        limit=1,
    )

    assert len(selected) == 1


def test_zero_history_limit_is_rejected_by_config():
    with pytest.raises(ValueError, match="history_limit"):
        TrendlineFeatureConfig(history_limit=0)


def test_negative_history_limit_is_rejected_by_config():
    with pytest.raises(ValueError, match="history_limit"):
        TrendlineFeatureConfig(history_limit=-1)


def test_bar_available_at_without_provenance_is_rejected():
    frame = _make_frame(40)
    frame["bar_available_at"] = frame.index + pd.Timedelta(hours=1)

    with pytest.raises(ValueError, match="provenance"):
        _resolve_bar_availability(
            frame,
            timeframe="1h",
            timestamp_semantics=BarTimestampSemantics.OPEN_TIME,
        )


def test_unknown_bar_availability_provenance_is_rejected():
    frame = _make_frame(40)
    frame["bar_available_at"] = frame.index + pd.Timedelta(hours=1)
    frame.attrs["bar_availability_source"] = "invented_source"

    with pytest.raises(ValueError, match="unknown"):
        _resolve_bar_availability(
            frame,
            timeframe="1h",
            timestamp_semantics=BarTimestampSemantics.OPEN_TIME,
        )


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
