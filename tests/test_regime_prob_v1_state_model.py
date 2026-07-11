from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM

from libs.models.regime_prob_v1.orchestrator import (
    RegimeProbOrchestratorConfig,
    RegimeProbV1Orchestrator,
)
from libs.models.regime_prob_v1.state import HMMStateModel, HMMStateModelConfig


def _state_feature_frame(n: int = 360) -> pd.DataFrame:
    rng = np.random.default_rng(31)
    idx = pd.date_range("2026-02-01", periods=n, freq="h", tz="UTC")
    segment = n // 4
    rows: list[dict[str, float | bool]] = []
    profiles = (
        {
            "trend_strength": 0.88,
            "trend_persistence": 0.86,
            "trend_confidence": 0.82,
            "volatility_percentile": 55.0,
            "compression_score": 0.20,
            "shock_risk": 0.18,
            "mean_reversion_score": 0.12,
            "range_quality": 0.20,
            "chop_risk": 0.12,
            "structural_break_risk": 0.15,
            "breakout_quality": 0.28,
            "false_breakout_risk": 0.12,
            "confidence": 0.84,
            "uncertainty": 0.14,
            "changepoint_prob": 0.12,
            "cp_recent_max": 0.12,
            "transition_risk_raw": 0.14,
            "hurst": 0.68,
            "raw_chop_risk": 0.10,
            "pre_breakout_setup_score": 0.22,
            "displacement_breakout_score": 0.20,
            "volume_confirmation": 0.18,
            "liquidity_stress": 0.10,
        },
        {
            "trend_strength": 0.18,
            "trend_persistence": 0.22,
            "trend_confidence": 0.20,
            "volatility_percentile": 36.0,
            "compression_score": 0.74,
            "shock_risk": 0.12,
            "mean_reversion_score": 0.78,
            "range_quality": 0.82,
            "chop_risk": 0.56,
            "structural_break_risk": 0.14,
            "breakout_quality": 0.14,
            "false_breakout_risk": 0.16,
            "confidence": 0.72,
            "uncertainty": 0.26,
            "changepoint_prob": 0.12,
            "cp_recent_max": 0.10,
            "transition_risk_raw": 0.12,
            "hurst": 0.44,
            "raw_chop_risk": 0.62,
            "pre_breakout_setup_score": 0.12,
            "displacement_breakout_score": 0.10,
            "volume_confirmation": 0.12,
            "liquidity_stress": 0.10,
        },
        {
            "trend_strength": 0.58,
            "trend_persistence": 0.52,
            "trend_confidence": 0.62,
            "volatility_percentile": 70.0,
            "compression_score": 0.34,
            "shock_risk": 0.28,
            "mean_reversion_score": 0.16,
            "range_quality": 0.20,
            "chop_risk": 0.22,
            "structural_break_risk": 0.68,
            "breakout_quality": 0.86,
            "false_breakout_risk": 0.18,
            "confidence": 0.78,
            "uncertainty": 0.22,
            "changepoint_prob": 0.34,
            "cp_recent_max": 0.38,
            "transition_risk_raw": 0.30,
            "hurst": 0.60,
            "raw_chop_risk": 0.18,
            "pre_breakout_setup_score": 0.74,
            "displacement_breakout_score": 0.82,
            "volume_confirmation": 0.72,
            "liquidity_stress": 0.12,
        },
        {
            "trend_strength": 0.16,
            "trend_persistence": 0.18,
            "trend_confidence": 0.22,
            "volatility_percentile": 92.0,
            "compression_score": 0.26,
            "shock_risk": 0.88,
            "mean_reversion_score": 0.16,
            "range_quality": 0.18,
            "chop_risk": 0.42,
            "structural_break_risk": 0.78,
            "breakout_quality": 0.30,
            "false_breakout_risk": 0.26,
            "confidence": 0.48,
            "uncertainty": 0.82,
            "changepoint_prob": 0.84,
            "cp_recent_max": 0.88,
            "transition_risk_raw": 0.84,
            "hurst": 0.36,
            "raw_chop_risk": 0.36,
            "pre_breakout_setup_score": 0.18,
            "displacement_breakout_score": 0.22,
            "volume_confirmation": 0.20,
            "liquidity_stress": 0.64,
        },
    )
    for profile in profiles:
        for _ in range(segment):
            row = {}
            for key, value in profile.items():
                noise = 0.0 if key == "volatility_percentile" else 0.035
                candidate = value + rng.normal(0.0, noise)
                if key == "volatility_percentile":
                    row[key] = float(np.clip(candidate, 5.0, 99.0))
                else:
                    row[key] = float(np.clip(candidate, 0.0, 1.0))
            row["row_quality_usable"] = True
            rows.append(row)
    frame = pd.DataFrame(rows, index=idx[: len(rows)])
    return frame


def _edge_frame(index: pd.Index) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "p_trend_following_edge": 0.74,
            "p_breakout_edge": 0.52,
            "p_mean_reversion_edge": 0.40,
            "p_scalping_edge": 0.18,
            "p_countertrend_edge": 0.24,
            "trend_following_p_edge_h3": 0.74,
            "breakout_p_edge_h3": 0.52,
            "mean_reversion_p_edge_h3": 0.40,
            "scalping_p_edge_h3": 0.18,
            "countertrend_p_edge_h3": 0.24,
        },
        index=index,
    )


def _ohlcv(n: int) -> pd.DataFrame:
    idx = pd.date_range("2026-02-01", periods=n, freq="h", tz="UTC")
    close = np.linspace(100.0, 120.0, n)
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * 1.002
    low = np.minimum(open_, close) * 0.998
    volume = np.full(n, 1500.0)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def test_hmm_state_model_emits_semantic_probabilities_and_latent_columns():
    feature_frame = _state_feature_frame()
    model = HMMStateModel(
        HMMStateModelConfig(
            min_train_bars=60,
            retrain_window=120,
            hmm_n_states=3,
            hmm_covariance_type="diag",
            hmm_robust_scoring=False,
        )
    )

    result = model.analyze(feature_frame)

    assert result.state_source == "hmm_state_model"
    assert result.diagnostics["ready"] is True
    assert {"p_trend_state", "p_transition_state", "hmm_p_state_0", "hmm_n_states"} <= set(result.frame.columns)
    probs = result.frame.loc[:, [
        "p_trend_state",
        "p_range_state",
        "p_chop_state",
        "p_breakout_state",
        "p_vol_shock_state",
        "p_transition_state",
    ]]
    assert np.allclose(probs.sum(axis=1), 1.0, atol=1e-6)
    assert result.frame["hmm_n_states"].max() >= 2.0
    assert result.frame["transition_matrix_self_prob"].between(0.0, 1.0).all()
    assert result.frame["latent_state_entropy"].between(0.0, 1.0).all()
    assert result.frame["hmm_state_eval_mode"].isin({"in_sample_fit", "oos_filtered", "proxy_fallback"}).all()


def test_hmm_state_model_is_prefix_consistent_for_same_fitted_model():
    feature_frame = _state_feature_frame()
    model = HMMStateModel(
        HMMStateModelConfig(
            min_train_bars=60,
            retrain_window=120,
            hmm_n_states=3,
            hmm_covariance_type="diag",
            hmm_robust_scoring=False,
        )
    )
    feature_matrix = model._build_feature_matrix(feature_frame)
    assert feature_matrix is not None
    matrix, _, _ = feature_matrix
    fitted = model._fit_gaussian_hmm(matrix[:180], n_states=3)

    prefix = model._get_proba(matrix[:120], fitted)
    extended = model._get_proba(matrix[:180], fitted)

    assert np.allclose(prefix, extended[:120], atol=1e-9)


def test_hmm_state_model_non_robust_runtime_output_does_not_call_predict_proba():
    feature_frame = _state_feature_frame()
    model = HMMStateModel(
        HMMStateModelConfig(
            min_train_bars=60,
            retrain_window=120,
            hmm_n_states=3,
            hmm_covariance_type="diag",
            hmm_robust_scoring=False,
        )
    )

    with patch.object(GaussianHMM, "predict_proba", side_effect=AssertionError("predict_proba should not be used")):
        result = model.analyze(feature_frame)

    assert result.state_source == "hmm_state_model"
    assert result.frame["latent_state_entropy"].between(0.0, 1.0).all()


def test_hmm_state_model_marks_first_segment_in_sample_and_later_segments_oos_filtered():
    feature_frame = _state_feature_frame()
    model = HMMStateModel(
        HMMStateModelConfig(
            min_train_bars=60,
            retrain_window=120,
            hmm_n_states=3,
            hmm_covariance_type="diag",
            hmm_robust_scoring=False,
        )
    )

    result = model.analyze(feature_frame)

    assert result.frame["hmm_state_eval_mode"].iloc[0] == "in_sample_fit"
    assert result.frame["hmm_state_eval_mode"].iloc[119] == "in_sample_fit"
    assert result.frame["hmm_state_eval_mode"].iloc[120] == "oos_filtered"
    assert result.frame["hmm_state_eval_mode"].iloc[-1] == "oos_filtered"
    assert result.diagnostics["hmm_in_sample_rows"] == 120
    assert result.diagnostics["hmm_oos_filtered_rows"] == 240
    assert result.diagnostics["hmm_proxy_fallback_rows"] == 0


def test_hmm_state_model_falls_back_to_proxy_when_history_is_too_short():
    feature_frame = _state_feature_frame(48)
    model = HMMStateModel(
        HMMStateModelConfig(
            min_train_bars=80,
            retrain_window=80,
            hmm_n_states=3,
        )
    )

    result = model.analyze(feature_frame)

    assert result.state_source == "deterministic_proxy_fallback"
    assert result.diagnostics["ready"] is False
    assert result.frame["hmm_n_states"].iloc[-1] == 2.0
    assert result.frame["p_transition_state"].between(0.0, 1.0).all()
    assert set(result.frame["hmm_state_eval_mode"].unique()) == {"proxy_fallback"}
    assert result.diagnostics["hmm_proxy_fallback_rows"] == len(feature_frame)


def test_hmm_state_model_falls_back_when_fitted_parameters_are_invalid():
    feature_frame = _state_feature_frame()
    model = HMMStateModel(
        HMMStateModelConfig(
            min_train_bars=60,
            retrain_window=120,
            hmm_n_states=3,
            hmm_covariance_type="diag",
        )
    )

    with patch.object(HMMStateModel, "_validate_fitted_model", side_effect=ValueError("invalid fitted parameters")):
        result = model.analyze(feature_frame)

    assert result.state_source == "deterministic_proxy_fallback"
    assert result.diagnostics["ready"] is False
    assert result.diagnostics["reason"] == "no_rows_classified"


def test_orchestrator_can_opt_into_hmm_state_source_without_changing_default_mode():
    feature_frame = _state_feature_frame()
    edge_frame = _edge_frame(feature_frame.index)
    df = _ohlcv(len(feature_frame))
    config = RegimeProbOrchestratorConfig(
        state_model_config=HMMStateModelConfig(
            min_train_bars=60,
            retrain_window=120,
            hmm_n_states=3,
            hmm_covariance_type="diag",
            hmm_robust_scoring=False,
        )
    )
    orchestrator = RegimeProbV1Orchestrator("BTCUSDT", "1h", config=config)

    with patch.object(orchestrator, "_build_feature_frame", return_value=feature_frame):
        with patch.object(orchestrator, "_build_edge_probability_frame", return_value=edge_frame):
            frame = orchestrator.analyze_series(df)
            latest = orchestrator.analyze(df)

    assert frame["diagnostics_state_source"].iloc[-1] == "hmm_state_model"
    assert "latent-state model" in frame["diagnostics_state_source_note"].iloc[-1]
    assert "hmm_p_state_0" in frame.columns
    assert "hmm_state_eval_mode" in frame.columns
    assert frame["transition_matrix_self_prob"].iloc[-1] >= 0.0
    assert latest.diagnostics["state_source"] == "hmm_state_model"
    assert latest.diagnostics["runtime"]["mode"] == "shadow"
    assert latest.diagnostics["runtime"]["can_force_trade"] is False
    assert latest.diagnostics["state_model"]["hmm_in_sample_rows"] == 120
    assert latest.diagnostics["state_model"]["hmm_oos_filtered_rows"] == 240
