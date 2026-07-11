from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd

from libs.models.regime_prob_v1.edge import EmpiricalCalibratorModel
from libs.models.regime_prob_v1.orchestrator import RegimeProbV1Orchestrator


def _make_ohlcv(n: int = 260, *, trend: float = 0.0025, noise: float = 0.0008) -> pd.DataFrame:
    rng = np.random.default_rng(17)
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    returns = trend + rng.normal(0.0, noise, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * 1.004
    low = np.minimum(open_, close) * 0.996
    volume = 1200.0 + rng.normal(0.0, 25.0, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def _trend_calibrator(high: float = 0.82) -> EmpiricalCalibratorModel:
    return EmpiricalCalibratorModel(
        strategy="quantile",
        bin_edges=(0.0, 0.5, 1.0),
        bin_probabilities=(0.20, high),
        counts=(16, 24),
        global_rate=0.50,
        min_bin_count=1,
    )


def _overlay_feature_frame(index: pd.Index, **overrides: float | bool) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "trend_strength": 1.0,
            "trend_confidence": 1.0,
            "range_quality": 0.0,
            "breakout_quality": 0.0,
            "chop_risk": 0.0,
            "shock_risk": 0.0,
            "structural_break_risk": 0.0,
            "uncertainty": 0.0,
            "changepoint_prob": 0.0,
            "cp_recent_max": 0.0,
            "transition_risk_raw": 0.0,
            "volume_confirmation": 0.0,
            "row_quality_usable": True,
            "policy_allow_trend_following": True,
            "policy_allow_breakout": True,
            "policy_allow_mean_reversion": True,
            "policy_allow_scalping": True,
            "policy_allow_countertrend": True,
            "policy_trend_score": 0.8,
            "policy_breakout_score": 0.2,
            "policy_mean_reversion_score": 0.4,
            "policy_scalping_score": 0.1,
            "policy_countertrend_score": 0.2,
            "external_context_coverage_ratio": 1.0,
            "external_context_staleness_bars": 0.0,
            "market_alignment_score": 0.0,
            "btc_d_conflict_score": 0.0,
            "total3_confirmation": 0.0,
            "asset_beta_btc": 0.8,
            "asset_beta_eth": 0.6,
        },
        index=index,
    )
    for key, value in overrides.items():
        frame[key] = value
    return frame


def _overlay_edge_frame(index: pd.Index, *, trend: float = 0.8, mean_reversion: float = 0.35) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "p_trend_following_edge": trend,
            "p_breakout_edge": 0.25,
            "p_mean_reversion_edge": mean_reversion,
            "p_scalping_edge": 0.10,
            "p_countertrend_edge": 0.15,
            "trend_following_p_edge_h3": trend,
            "breakout_p_edge_h3": 0.25,
            "mean_reversion_p_edge_h3": mean_reversion,
            "scalping_p_edge_h3": 0.10,
            "countertrend_p_edge_h3": 0.15,
        },
        index=index,
    )


def test_orchestrator_emits_probability_frame_and_runtime_output():
    df = _make_ohlcv()
    orchestrator = RegimeProbV1Orchestrator(
        "BTCUSDT",
        "1h",
        calibrators={"trend_following": _trend_calibrator()},
    )

    frame = orchestrator.analyze_series(df)
    latest = orchestrator.analyze(df)

    assert {"p_trend_state", "state_entropy", "p_trend_following_edge", "trend_following_p_edge_h3", "recommended_playbook"} <= set(frame.columns)
    assert frame["p_trend_following_edge"].iloc[-1] >= 0.0
    assert abs(sum(latest.moe_weights.values()) - 1.0) < 1e-6 or sum(latest.moe_weights.values()) == 0.0
    assert frame["diagnostics_state_source"].iloc[-1] == "deterministic_proxy"
    assert "not a true HMM posterior" in frame["diagnostics_state_source_note"].iloc[-1]
    assert latest.diagnostics["state_source"] == "deterministic_proxy"
    assert "not a true HMM posterior" in latest.diagnostics["state_source_note"]
    assert latest.diagnostics["research_only"] is True


def test_orchestrator_runtime_contract_defaults_to_shadow_and_no_force_trade():
    orchestrator = RegimeProbV1Orchestrator("BTCUSDT", "1h")

    assert orchestrator.config.runtime.mode == "shadow"
    assert orchestrator.config.runtime.can_force_trade is False
    assert orchestrator.config.runtime.fallback_to_regime_v2 is True


def test_orchestrator_without_calibrators_stays_neutral():
    df = _make_ohlcv()
    orchestrator = RegimeProbV1Orchestrator("BTCUSDT", "1h")

    latest = orchestrator.analyze(df)

    assert latest.recommended_playbook is None
    assert all(value == 0.0 for value in latest.moe_weights.values())
    assert latest.p_trend_following_edge == 0.0
    assert "trend_following" in latest.diagnostics["missing_calibrators"]


def test_orchestrator_surfaces_mtf_context_when_higher_timeframe_frames_are_supplied():
    df = _make_ohlcv()
    calibrators = {"trend_following": _trend_calibrator()}
    ltf = RegimeProbV1Orchestrator("BTCUSDT", "1h", calibrators=calibrators)
    htf_index = pd.date_range(df.index[0], periods=80, freq="4h", tz="UTC")
    htf_frame = pd.DataFrame(
        {
            "p_trend_state": 0.78,
            "p_range_state": 0.06,
            "p_chop_state": 0.04,
            "p_breakout_state": 0.08,
            "p_vol_shock_state": 0.02,
            "p_transition_state": 0.02,
            "state_entropy": 0.22,
            "trend_following_p_edge_h3": 0.80,
            "breakout_p_edge_h3": 0.20,
            "mean_reversion_p_edge_h3": 0.10,
        },
        index=htf_index,
    )

    frame = ltf.analyze_series(df, higher_timeframe_probability_frames={"4h": htf_frame})
    latest = ltf.analyze(df, higher_timeframe_probability_frames={"4h": htf_frame})

    assert "mtf_trend_confirmation" in frame.columns
    assert latest.mtf_context["mtf_trend_confirmation"] is not None
    assert latest.diagnostics["mtf_enabled"] is True


def test_orchestrator_overlay_suppresses_router_when_transition_risk_is_high():
    df = _make_ohlcv(1)
    feature_frame = _overlay_feature_frame(
        df.index,
        structural_break_risk=0.95,
        uncertainty=0.95,
        changepoint_prob=0.95,
        cp_recent_max=0.95,
        transition_risk_raw=0.95,
    )
    edge_frame = _overlay_edge_frame(df.index)
    orchestrator = RegimeProbV1Orchestrator("BTCUSDT", "1h")

    with patch.object(orchestrator, "_build_feature_frame", return_value=feature_frame):
        with patch.object(orchestrator, "_build_edge_probability_frame", return_value=edge_frame):
            frame = orchestrator.analyze_series(df)
            latest = orchestrator.analyze(df)

    assert bool(frame.iloc[-1]["overlay_gate_active"]) is False
    assert frame.iloc[-1]["recommended_playbook"] is None
    assert latest.recommended_playbook is None
    assert sum(latest.moe_weights.values()) == 0.0


def test_orchestrator_overlay_columns_reflect_external_context_adjustment():
    df = _make_ohlcv(1)
    feature_frame = _overlay_feature_frame(
        df.index,
        market_alignment_score=-1.0,
        btc_d_conflict_score=1.0,
        total3_confirmation=-1.0,
    )
    edge_frame = _overlay_edge_frame(df.index)
    orchestrator = RegimeProbV1Orchestrator("BTCUSDT", "1h")

    with patch.object(orchestrator, "_build_feature_frame", return_value=feature_frame):
        with patch.object(orchestrator, "_build_edge_probability_frame", return_value=edge_frame):
            frame = orchestrator.analyze_series(df)

    assert "overlay_trend_following_p_edge_h3" in frame.columns
    assert frame.iloc[-1]["overlay_trend_following_p_edge_h3"] < frame.iloc[-1]["trend_following_p_edge_h3"]
    assert bool(frame.iloc[-1]["overlay_gate_active"]) is True
