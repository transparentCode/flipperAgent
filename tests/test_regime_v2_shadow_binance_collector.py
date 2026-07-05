"""Tests for the offline Binance RegimeV2 shadow-log collector."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.scripts.collect_shadow_binance import (
    _feature_vector_from_row,
    _force_shadow_persistence,
    _outputs_from_candidates,
    _parse_args,
    _parse_pairs,
)


def test_parse_pairs_defaults_to_phase5d_rollout_pairs():
    assert _parse_pairs(None) == (
        ("BTCUSDT", "4h"),
        ("ETHUSDT", "4h"),
        ("SOLUSDT", "4h"),
        ("BNBUSDT", "1h"),
    )


def test_parse_pairs_normalizes_symbol():
    assert _parse_pairs(["btcusdt:4h", "ethusdt:1h"]) == (("BTCUSDT", "4h"), ("ETHUSDT", "1h"))


def test_outputs_from_candidates_preserves_threshold_and_signed_scoring():
    ts = pd.Timestamp("2026-01-01T00:00:00Z")
    frame = pd.DataFrame(
        [
            {
                "timestamp": ts,
                "model_name": "Momentum",
                "asset": "BTCUSDT",
                "timeframe": "4h",
                "direction": 1,
                "edge_score": 1.0,
                "conviction": 0.8,
                "source_type": "threshold",
            },
            {
                "timestamp": ts,
                "model_name": "RegimePullbackScorer",
                "asset": "BTCUSDT",
                "timeframe": "4h",
                "direction": -1,
                "edge_score": 0.4,
                "conviction": 0.4,
                "source_type": "scoring",
            },
        ]
    )

    model_outputs, scoring_outputs = _outputs_from_candidates(frame)

    assert len(model_outputs) == 1
    assert model_outputs[0].model_name == "Momentum"
    assert model_outputs[0].direction == 1
    assert len(scoring_outputs) == 1
    assert scoring_outputs[0].model_name == "RegimePullbackScorer"
    assert scoring_outputs[0].edge_score == -0.4


def test_feature_vector_from_regime_comparison_row_builds_nested_payload():
    ts = pd.Timestamp("2026-01-01T00:00:00Z")
    comparison_row = pd.Series(
        {
            "regime_v2_trend_direction": "bull",
            "regime_v2_confidence": 0.7,
            "regime_v2_uncertainty": 0.2,
            "regime_v2_policy_allow_trend_following": True,
            "regime_v2_policy_allow_breakout": True,
            "regime_v2_policy_allow_mean_reversion": False,
            "regime_v2_policy_trend_score": 0.6,
            "regime_v2_policy_breakout_score": 0.5,
            "regime_v2_policy_mean_reversion_score": 0.1,
        }
    )
    ohlcv_row = pd.Series({"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10})

    fv = _feature_vector_from_row(
        comparison_row,
        ohlcv_row,
        asset="BTCUSDT",
        timeframe="4h",
        timestamp=ts,
    )

    assert fv.asset == "BTCUSDT"
    assert fv.timeframe == "4h"
    assert fv.timestamp == ts.timestamp()
    assert fv.features["regime_v2"]["evidence"]["trend_direction"] == "bull"
    assert fv.features["regime_v2"]["policy"]["allow_trend_following"] is True
    assert fv.features["regime_v2"]["policy"]["mean_reversion_score"] == 0.1
    assert fv.bar_data["close"] == 1.5


def test_feature_vector_from_row_attaches_optional_trendline_payload():
    ts = pd.Timestamp("2026-01-01T00:00:00Z")
    fv = _feature_vector_from_row(
        pd.Series({}),
        pd.Series({"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10}),
        asset="BTCUSDT",
        timeframe="4h",
        timestamp=ts,
        trendline_features={
            "trendline_valid": 1.0,
            "trendline_market_position_state": "inside_channel",
        },
    )

    assert fv.features["trendline"]["trendline_valid"] == 1.0
    assert fv.features["trendline"]["trendline_market_position_state"] == "inside_channel"


def test_force_shadow_persistence_sets_collector_log_path():
    class DummyLayer:
        def __init__(self) -> None:
            self._config = {"overlays": {"regime_v2_trend_gate": {"enabled": False}}}

    layer = DummyLayer()

    _force_shadow_persistence(layer, "/tmp/custom_shadow.jsonl")

    gate = layer._config["overlays"]["regime_v2_trend_gate"]
    assert gate["enabled"] is False
    assert gate["shadow_enabled"] is True
    assert gate["shadow_persist_enabled"] is True
    assert gate["shadow_persist_path"] == "/tmp/custom_shadow.jsonl"


def test_collect_shadow_binance_cli_parse_args():
    args = _parse_args(
        [
            "--pair",
            "btcusdt:4h",
            "--limit",
            "300",
            "--warmup-bars",
            "50",
            "--max-records-per-pair",
            "20",
            "--log-path",
            "logs/custom.jsonl",
            "--reset-log",
            "--include-trendline-context",
            "--trendline-min-bars",
            "40",
            "--trendline-history-limit",
            "3",
        ]
    )

    assert args.pair == ["btcusdt:4h"]
    assert args.limit == 300
    assert args.warmup_bars == 50
    assert args.max_records_per_pair == 20
    assert args.log_path == "logs/custom.jsonl"
    assert args.reset_log is True
    assert args.include_trendline_context is True
    assert args.trendline_min_bars == 40
    assert args.trendline_history_limit == 3
