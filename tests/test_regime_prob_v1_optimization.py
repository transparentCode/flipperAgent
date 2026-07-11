from __future__ import annotations

from unittest.mock import patch

import numpy as np
import optuna
import pandas as pd

from libs.models.regime_prob_v1 import (
    build_regime_prob_edge_labels,
    build_regime_prob_feature_frame,
    playbook_score_column,
)
from libs.models.regime_prob_v1.moe import PLAYBOOKS, playbook_probability_column
from libs.models.regime_prob_v1.optimization import objective as objective_module
from libs.models.regime_prob_v1.optimization import (
    RegimeProbOptimizationGates,
    RegimeProbRollingValidationConfig,
    RegimeProbValidationResult,
    RegimeProbWindowMetric,
    build_promotion_gate,
    evaluate_oos,
    evaluate_regime_prob_frame,
    expand_manifest_runs,
    extract_profile_defaults,
    format_deploy_params,
    get_optimization_param_schema,
    make_objective,
    post_process_params,
    render_markdown_report,
    run_study,
    run_threshold_sweep,
)
from libs.models.regime_prob_v1.optimization.threshold_sweep import DEFAULT_THRESHOLD_PARAMS


def _make_ohlcv(n: int = 260, *, trend: float = 0.003, noise: float = 0.001) -> pd.DataFrame:
    rng = np.random.default_rng(21)
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    returns = trend + rng.normal(0.0, noise, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * 1.004
    low = np.minimum(open_, close) * 0.996
    volume = 1000.0 + rng.normal(0.0, 20.0, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def _feature_and_labels() -> tuple[pd.DataFrame, pd.DataFrame]:
    df = _make_ohlcv()
    feature_frame = build_regime_prob_feature_frame(df, asset="BTCUSDT", timeframe="1h")
    labels = build_regime_prob_edge_labels(feature_frame, df, timeframe="1h")
    return feature_frame, labels.frame


def _probability_feature_frame(feature_frame: pd.DataFrame, *, horizon: int) -> pd.DataFrame:
    out = feature_frame.copy()
    for playbook in PLAYBOOKS:
        pcol = playbook_probability_column(playbook, horizon)
        score_col = playbook_score_column(playbook)
        out[pcol] = pd.to_numeric(out.get(score_col), errors="coerce").fillna(0.0).clip(0.0, 1.0)
    return out


def _hmm_state_feature_frame(
    feature_frame: pd.DataFrame,
    *,
    horizon: int,
    source: str = "hmm_state_model",
    eval_modes: pd.Series | str | None = None,
) -> pd.DataFrame:
    out = _probability_feature_frame(feature_frame, horizon=horizon)
    if eval_modes is None:
        eval_mode_series = pd.Series("oos_filtered", index=out.index, dtype=object)
    elif isinstance(eval_modes, pd.Series):
        eval_mode_series = eval_modes.reindex(out.index).fillna("proxy_fallback").astype(object)
    else:
        eval_mode_series = pd.Series(str(eval_modes), index=out.index, dtype=object)
    out["diagnostics_state_source"] = source
    out["hmm_state_eval_mode"] = eval_mode_series.astype(str)
    out["p_trend_state"] = 0.92
    out["p_range_state"] = 0.02
    out["p_chop_state"] = 0.02
    out["p_breakout_state"] = 0.02
    out["p_vol_shock_state"] = 0.01
    out["p_transition_state"] = 0.01
    out["state_entropy"] = 0.10
    out["dominant_state"] = "trend"
    out["dominant_state_prob"] = 0.92
    out["hmm_transition_prob"] = 0.05
    out["hmm_crisis_prob"] = 0.01
    out["transition_matrix_self_prob"] = 0.95
    out["latent_state_entropy"] = 0.15
    out["posterior_shift"] = 0.03
    return out


def _external_context_feature_frame(feature_frame: pd.DataFrame, *, horizon: int) -> pd.DataFrame:
    out = _probability_feature_frame(feature_frame, horizon=horizon)
    out["total3_confirmation"] = 0.40
    out["market_alignment_score"] = 0.25
    out["btc_d_conflict_score"] = 0.10
    out["external_context_coverage_ratio"] = 1.00
    out["external_context_staleness_bars"] = 1.00
    out["asset_beta_btc"] = 0.80
    out["asset_beta_eth"] = 0.60
    return out


def _mtf_context_frame(index: pd.Index) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "mtf_trend_confirmation": 0.75,
            "mtf_breakout_confirmation": 0.35,
            "mtf_mr_confirmation": 0.15,
            "mtf_conflict_score": 0.10,
            "mtf_entropy_max": 0.40,
            "mtf_transition_max": 0.05,
        },
        index=index,
    )


def _validation_config() -> RegimeProbRollingValidationConfig:
    return RegimeProbRollingValidationConfig(
        window_bars=80,
        step_bars=40,
        min_window_bars=40,
        gates=RegimeProbOptimizationGates(
            min_support_count=1,
            min_support_rate=0.0,
            min_positive_window_rate=0.0,
            min_mean_edge_return=-1.0,
            max_decision_flip_rate=1.0,
            max_threshold_churn=1.0,
            min_oos_score_ratio=0.25,
        ),
    )


def _oos_payload(
    *,
    score: float,
    mean_edge_return: float,
    positive_window_rate: float,
    deployed: bool = True,
    mean_brier_score: float = 0.10,
    mean_expected_calibration_error: float = 0.10,
    rejection_reasons: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "deployed": deployed,
        "rejection_reasons": list(rejection_reasons),
        "oos": {
            "aggregate": {
                "score": score,
                "mean_edge_return": mean_edge_return,
                "positive_window_rate": positive_window_rate,
                "mean_brier_score": mean_brier_score,
                "mean_expected_calibration_error": mean_expected_calibration_error,
            }
        },
    }


def test_param_schema_exposes_expected_profiles():
    edge = get_optimization_param_schema("edge_calibration")
    state = get_optimization_param_schema("state_core")
    transition = get_optimization_param_schema("transition")
    router = get_optimization_param_schema("moe_router")
    external = get_optimization_param_schema("external_context")
    full = get_optimization_param_schema("full_shadow_only")

    assert {"n_bins", "min_bin_count", "strategy", "active_probability_threshold"} <= set(edge)
    assert {"min_edge_probability", "min_trend_state_prob", "max_state_entropy"} <= set(state)
    assert {"transition_risk_threshold", "uncertainty_threshold", "changepoint_prob_threshold"} <= set(transition)
    assert {"min_edge_probability", "top_k", "recommendation_min_probability"} <= set(router)
    assert {"max_staleness_bars", "total3_confirmation_weight", "context_staleness_penalty"} <= set(external)
    assert {"n_bins", "higher_tf_weight", "max_staleness_bars"} <= set(full)
    assert edge["active_probability_threshold"].default == 0.35
    assert state["min_trend_state_prob"].default == 0.45
    assert transition["transition_risk_threshold"].default == 0.55
    assert edge["active_probability_threshold"].low == 0.25
    assert router["min_edge_probability"].default == 0.35
    assert router["recommendation_min_probability"].low == 0.25
    assert external["max_staleness_bars"].default == 2


def test_threshold_sweep_defaults_cover_all_executable_profiles():
    assert {
        "state_core",
        "transition",
        "edge_calibration",
        "moe_router",
        "mtf_overlay",
        "external_context",
        "full_shadow_only",
    } <= set(DEFAULT_THRESHOLD_PARAMS)
    assert "transition_risk_threshold" in DEFAULT_THRESHOLD_PARAMS["transition"]
    assert "total3_confirmation_weight" in DEFAULT_THRESHOLD_PARAMS["external_context"]
    assert "higher_tf_weight" in DEFAULT_THRESHOLD_PARAMS["full_shadow_only"]


def test_validation_scores_supported_decision_frame():
    n = 80
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    active = np.zeros(n, dtype=bool)
    active[:24] = True
    frame = pd.DataFrame(
        {
            "selected_probability": np.where(active, 0.8, 0.2),
            "selected_label": np.where(active, 1.0, 0.0),
            "selected_edge_return": np.where(active, 0.03, -0.005),
            "decision_active": active,
            "decision_key": np.where(active, "trend_following", "flat"),
        },
        index=idx,
    )

    result = evaluate_regime_prob_frame(frame, config=_validation_config())

    assert result.rejected is False
    assert result.score > 0.0
    assert result.aggregate["positive_window_rate"] == 1.0


def test_validation_rejects_negative_edge_candidates():
    n = 80
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "selected_probability": 0.75,
            "selected_label": 0.65,
            "selected_edge_return": -0.01,
            "decision_active": True,
            "decision_key": "trend_following",
        },
        index=idx,
    )

    result = evaluate_regime_prob_frame(
        frame,
        config=RegimeProbRollingValidationConfig(
            window_bars=40,
            step_bars=20,
            min_window_bars=40,
            gates=RegimeProbOptimizationGates(
                min_support_count=1,
                min_support_rate=0.0,
                min_positive_window_rate=0.0,
                min_mean_edge_return=0.0,
                max_decision_flip_rate=1.0,
                max_threshold_churn=1.0,
                min_oos_score_ratio=0.25,
            ),
        ),
    )

    assert result.rejected is True
    assert "mean_edge_return_below_minimum" in result.rejection_reasons


def test_make_objective_accepts_fixed_trial_and_records_metrics():
    feature_frame, label_frame = _feature_and_labels()
    defaults = extract_profile_defaults("edge_calibration")
    objective = make_objective(
        feature_frame,
        label_frame,
        profile="edge_calibration",
        playbook="trend_following",
        horizon=3,
        validation_config=_validation_config(),
    )
    trial = optuna.trial.FixedTrial(defaults)

    score = objective(trial)

    assert isinstance(score, float)
    assert "regime_prob_validation" in trial.user_attrs


def test_evaluate_oos_and_deploy_format_use_processed_params():
    feature_frame, label_frame = _feature_and_labels()
    params = {
        "n_bins": 8.4,
        "min_bin_count": 6.6,
        "strategy": "quantile",
        "active_probability_threshold": 0.56,
    }

    processed = post_process_params(params, profile="edge_calibration")
    deploy = format_deploy_params(params, profile="edge_calibration")
    result = evaluate_oos(
        feature_frame,
        label_frame,
        processed,
        profile="edge_calibration",
        playbook="trend_following",
        horizon=3,
        validation_config=_validation_config(),
    )

    assert processed["n_bins"] == 8
    assert deploy["params"]["active_probability_threshold"] == 0.56
    assert set(result) >= {"train", "calibration", "validation", "oos", "deployed", "params"}


def test_evaluate_oos_marks_validation_rejections_non_deployable():
    feature_frame, label_frame = _feature_and_labels()
    decision_frame = pd.DataFrame(
        {
            "temporal_segment": ["train", "calibration", "validation", "validation", "oos", "oos"],
            "selected_probability": [0.7, 0.7, 0.7, 0.7, 0.7, 0.7],
            "selected_label": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            "selected_edge_return": [0.01, 0.01, 0.01, 0.01, 0.01, 0.01],
            "decision_active": [True, True, True, True, True, True],
            "decision_key": ["trend_following"] * 6,
        },
        index=feature_frame.index[:6],
    )
    validation_result = RegimeProbValidationResult(
        score=-0.01,
        rejected=True,
        rejection_reasons=("mean_edge_return_below_minimum",),
        windows=(RegimeProbWindowMetric(0, 2, 2, 1.0, -0.01, 0.5, 0.0, 0.0, 0.1, 0.1, -0.01),),
        aggregate={
            "score": -0.01,
            "window_count": 1,
            "positive_window_rate": 0.0,
            "mean_support_count": 2.0,
            "mean_support_rate": 1.0,
            "mean_edge_return": -0.01,
            "mean_positive_rate": 0.5,
            "mean_brier_score": 0.1,
            "mean_expected_calibration_error": 0.1,
            "mean_decision_flip_rate": 0.0,
            "mean_threshold_churn": 0.0,
        },
    )
    oos_result = RegimeProbValidationResult(
        score=0.05,
        rejected=False,
        rejection_reasons=(),
        windows=(RegimeProbWindowMetric(0, 2, 2, 1.0, 0.01, 1.0, 0.0, 0.0, 0.1, 0.1, 0.05),),
        aggregate={
            "score": 0.05,
            "window_count": 1,
            "positive_window_rate": 1.0,
            "mean_support_count": 2.0,
            "mean_support_rate": 1.0,
            "mean_edge_return": 0.01,
            "mean_positive_rate": 1.0,
            "mean_brier_score": 0.1,
            "mean_expected_calibration_error": 0.1,
            "mean_decision_flip_rate": 0.0,
            "mean_threshold_churn": 0.0,
        },
    )

    with patch("libs.models.regime_prob_v1.optimization.objective.build_decision_frame", return_value=decision_frame):
        with patch(
            "libs.models.regime_prob_v1.optimization.objective.evaluate_regime_prob_frame",
            side_effect=[oos_result, oos_result, validation_result, oos_result],
        ):
            result = evaluate_oos(
                feature_frame,
                label_frame,
                extract_profile_defaults("edge_calibration"),
                profile="edge_calibration",
                playbook="trend_following",
                horizon=3,
                validation_config=_validation_config(),
            )

    assert result["deployed"] is False
    assert result["validation_rejected"] is True
    assert result["oos_rejected"] is False
    assert "validation:mean_edge_return_below_minimum" in result["rejection_reasons"]
    assert result["validation_rejection_reasons"] == ["validation:mean_edge_return_below_minimum"]
    assert result["oos_rejection_reasons"] == []


def test_promotion_gate_requires_default_vs_tuned_lift_and_quality():
    baseline = _oos_payload(
        score=0.11,
        mean_edge_return=0.020,
        positive_window_rate=0.70,
        mean_brier_score=0.08,
        mean_expected_calibration_error=0.05,
    )
    tuned = _oos_payload(
        score=0.11,
        mean_edge_return=0.018,
        positive_window_rate=0.68,
        mean_brier_score=0.09,
        mean_expected_calibration_error=0.06,
    )

    gate = build_promotion_gate(baseline, tuned)

    assert gate["ready"] is False
    assert "oos_score_not_above_baseline" in gate["rejection_reasons"]
    assert "mean_edge_return_not_above_baseline" in gate["rejection_reasons"]
    assert "positive_window_rate_regressed" in gate["rejection_reasons"]
    assert "brier_score_regressed" in gate["rejection_reasons"]
    assert "expected_calibration_error_regressed" in gate["rejection_reasons"]


def test_objective_module_uses_shared_overlay_helpers_only():
    assert not hasattr(objective_module, "_proxy_state_frame")
    assert not hasattr(objective_module, "_state_entropy")
    assert not hasattr(objective_module, "_transition_risk_series")
    assert not hasattr(objective_module, "_apply_external_context_overlay")


def test_state_core_uses_hmm_state_frame_only_when_explicitly_enabled():
    feature_frame, label_frame = _feature_and_labels()
    probability_frame = _probability_feature_frame(feature_frame, horizon=3)
    hmm_frame = _hmm_state_feature_frame(feature_frame, horizon=3)
    params = extract_profile_defaults("state_core")
    real_overlay = objective_module._build_probability_overlay
    captured: dict[str, pd.DataFrame | None] = {}

    def _spy_overlay(*args, **kwargs):
        state_frame = kwargs.get("state_frame")
        captured["state_frame"] = None if state_frame is None else state_frame.copy()
        return real_overlay(*args, **kwargs)

    with patch("libs.models.regime_prob_v1.optimization.objective._build_probability_overlay", side_effect=_spy_overlay):
        objective_module.build_decision_frame(
            hmm_frame,
            label_frame,
            params=params,
            profile="state_core",
            playbook=None,
            horizon=3,
        )
    assert captured["state_frame"] is not None
    assert captured["state_frame"]["p_trend_state"].eq(0.92).all()

    with patch("libs.models.regime_prob_v1.optimization.objective._build_probability_overlay", side_effect=_spy_overlay):
        objective_module.build_decision_frame(
            probability_frame,
            label_frame,
            params=params,
            profile="state_core",
            playbook=None,
            horizon=3,
        )
    assert captured["state_frame"] is None


def test_hmm_in_sample_rows_are_excluded_from_state_core_scoring():
    feature_frame, label_frame = _feature_and_labels()
    eval_modes = pd.Series("oos_filtered", index=feature_frame.index, dtype=object)
    validation_index = label_frame.index[label_frame["temporal_segment"].astype(str) == "validation"]
    eval_modes.loc[validation_index[:10]] = "in_sample_fit"
    hmm_frame = _hmm_state_feature_frame(feature_frame, horizon=3, eval_modes=eval_modes)
    decision_frame = objective_module.build_decision_frame(
        hmm_frame,
        label_frame,
        params=extract_profile_defaults("state_core"),
        profile="state_core",
        playbook=None,
        horizon=3,
    )
    validation_frame = decision_frame.loc[decision_frame["temporal_segment"].astype(str) == "validation"].copy()

    result = evaluate_regime_prob_frame(validation_frame, config=_validation_config())
    expected = evaluate_regime_prob_frame(
        validation_frame.loc[validation_frame["hmm_state_eval_mode"].astype(str) == "oos_filtered"].copy(),
        config=_validation_config(),
    )

    assert result.score == expected.score
    assert result.rejected == expected.rejected
    assert result.aggregate["hmm_oos_filtered_support_count"] == int(
        (validation_frame["hmm_state_eval_mode"].astype(str) == "oos_filtered").sum()
    )


def test_hmm_proxy_fallback_rows_are_excluded_from_hmm_aware_scoring():
    feature_frame, label_frame = _feature_and_labels()
    fallback_frame = _hmm_state_feature_frame(
        feature_frame,
        horizon=3,
        source="deterministic_proxy_fallback",
        eval_modes="proxy_fallback",
    )

    result = evaluate_oos(
        fallback_frame,
        label_frame,
        extract_profile_defaults("state_core"),
        profile="state_core",
        horizon=3,
        validation_config=_validation_config(),
    )

    assert result["deployed"] is False
    assert result["hmm_state_source"] == "deterministic_proxy_fallback"
    assert result["hmm_in_sample_rows"] == 0
    assert result["hmm_oos_filtered_rows"] == 0
    assert result["hmm_proxy_fallback_rows"] == len(fallback_frame)
    assert "validation:hmm_oos_filtered_support_below_minimum" in result["rejection_reasons"]


def test_low_hmm_oos_filtered_support_rejects_trial_or_config():
    feature_frame, label_frame = _feature_and_labels()
    eval_modes = pd.Series("in_sample_fit", index=feature_frame.index, dtype=object)
    validation_index = label_frame.index[label_frame["temporal_segment"].astype(str) == "validation"]
    oos_index = label_frame.index[label_frame["temporal_segment"].astype(str) == "oos"]
    eval_modes.loc[validation_index[:2]] = "oos_filtered"
    eval_modes.loc[oos_index[:2]] = "oos_filtered"
    hmm_frame = _hmm_state_feature_frame(feature_frame, horizon=3, eval_modes=eval_modes)
    cfg = RegimeProbRollingValidationConfig(
        window_bars=40,
        step_bars=20,
        min_window_bars=40,
        gates=RegimeProbOptimizationGates(
            min_support_count=5,
            min_support_rate=0.0,
            min_positive_window_rate=0.0,
            min_mean_edge_return=-1.0,
            max_decision_flip_rate=1.0,
            max_threshold_churn=1.0,
            min_oos_score_ratio=0.25,
        ),
    )

    result = evaluate_oos(
        hmm_frame,
        label_frame,
        extract_profile_defaults("state_core"),
        profile="state_core",
        horizon=3,
        validation_config=cfg,
    )

    assert result["deployed"] is False
    assert result["hmm_oos_filtered_rows"] == 4
    assert result["hmm_oos_filtered_support_rate"] > 0.0
    assert "validation:hmm_oos_filtered_support_below_minimum" in result["rejection_reasons"]


def test_hmm_state_profiles_reject_malformed_hmm_frames_without_proxy_overlay():
    feature_frame, label_frame = _feature_and_labels()
    malformed = _hmm_state_feature_frame(feature_frame, horizon=3).drop(
        columns=["p_trend_state", "p_range_state"],
    )
    params = extract_profile_defaults("state_core")

    with patch("libs.models.regime_prob_v1.optimization.objective._build_probability_overlay") as overlay:
        decision_frame = objective_module.build_decision_frame(
            malformed,
            label_frame,
            params=params,
            profile="state_core",
            playbook=None,
            horizon=3,
        )

    overlay.assert_not_called()
    assert decision_frame["hmm_state_error"].eq("hmm_state_columns_missing").all()

    result = evaluate_oos(
        malformed,
        label_frame,
        params,
        profile="state_core",
        horizon=3,
        validation_config=_validation_config(),
    )

    assert result["deployed"] is False
    assert "validation:hmm_state_columns_missing" in result["rejection_reasons"]


def test_full_shadow_activation_audit_reports_overlay_gate_inactive():
    feature_frame, label_frame = _feature_and_labels()
    hmm_frame = _hmm_state_feature_frame(feature_frame, horizon=3)
    params = {
        **extract_profile_defaults("full_shadow_only"),
        "min_edge_probability": 0.20,
        "recommendation_min_probability": 0.10,
        "require_policy_allow": False,
    }
    adjusted = pd.DataFrame(0.60, index=hmm_frame.index, columns=list(PLAYBOOKS))
    overlay_result = type(
        "OverlayResult",
        (),
        {
            "adjusted_probabilities": adjusted,
            "state_frame": hmm_frame[["p_trend_state", "p_range_state", "p_chop_state", "p_breakout_state", "p_vol_shock_state", "p_transition_state", "state_entropy"]],
            "transition_risk": pd.Series(0.10, index=hmm_frame.index),
            "gate_active": pd.Series(False, index=hmm_frame.index),
        },
    )()

    with patch("libs.models.regime_prob_v1.optimization.objective._build_probability_overlay", return_value=overlay_result):
        decision_frame = objective_module.build_decision_frame(
            hmm_frame,
            label_frame,
            params=params,
            profile="full_shadow_only",
            playbook=None,
            horizon=3,
        )

    audit = decision_frame["full_shadow_audit_final_reason"].value_counts().to_dict()
    summary = objective_module._full_shadow_activation_audit_summary(decision_frame)
    assert summary is not None

    assert audit == {"overlay_gate_inactive": len(decision_frame)}
    assert summary["overall"]["overlay_stage"]["overlay_gate_active_count"] == 0
    assert summary["overall"]["final_selection_stage"]["final_decision_active_count"] == 0


def test_full_shadow_activation_audit_reports_no_moe_recommendation():
    feature_frame, label_frame = _feature_and_labels()
    hmm_frame = _hmm_state_feature_frame(feature_frame, horizon=3)
    params = {
        **extract_profile_defaults("full_shadow_only"),
        "min_edge_probability": 0.80,
        "recommendation_min_probability": 0.80,
        "require_policy_allow": False,
    }
    adjusted = pd.DataFrame(0.10, index=hmm_frame.index, columns=list(PLAYBOOKS))
    overlay_result = type(
        "OverlayResult",
        (),
        {
            "adjusted_probabilities": adjusted,
            "state_frame": hmm_frame[["p_trend_state", "p_range_state", "p_chop_state", "p_breakout_state", "p_vol_shock_state", "p_transition_state", "state_entropy"]],
            "transition_risk": pd.Series(0.10, index=hmm_frame.index),
            "gate_active": pd.Series(True, index=hmm_frame.index),
        },
    )()

    with patch("libs.models.regime_prob_v1.optimization.objective._build_probability_overlay", return_value=overlay_result):
        decision_frame = objective_module.build_decision_frame(
            hmm_frame,
            label_frame,
            params=params,
            profile="full_shadow_only",
            playbook=None,
            horizon=3,
        )

    assert decision_frame["full_shadow_audit_final_reason"].eq("no_recommendation").all()
    assert decision_frame["full_shadow_audit_moe_has_recommendation"].eq(False).all()


def test_full_shadow_activation_audit_reports_score_below_min_edge_probability():
    feature_frame, label_frame = _feature_and_labels()
    hmm_frame = _hmm_state_feature_frame(feature_frame, horizon=3)
    params = {
        **extract_profile_defaults("full_shadow_only"),
        "min_edge_probability": 0.30,
        "recommendation_min_probability": 0.10,
        "require_policy_allow": False,
        "top_k": len(PLAYBOOKS),
    }
    adjusted = pd.DataFrame(0.31, index=hmm_frame.index, columns=list(PLAYBOOKS))
    overlay_result = type(
        "OverlayResult",
        (),
        {
            "adjusted_probabilities": adjusted,
            "state_frame": hmm_frame[["p_trend_state", "p_range_state", "p_chop_state", "p_breakout_state", "p_vol_shock_state", "p_transition_state", "state_entropy"]],
            "transition_risk": pd.Series(0.10, index=hmm_frame.index),
            "gate_active": pd.Series(True, index=hmm_frame.index),
        },
    )()

    with patch("libs.models.regime_prob_v1.optimization.objective._build_probability_overlay", return_value=overlay_result):
        decision_frame = objective_module.build_decision_frame(
            hmm_frame,
            label_frame,
            params=params,
            profile="full_shadow_only",
            playbook=None,
            horizon=3,
        )

    assert decision_frame["full_shadow_audit_moe_has_recommendation"].eq(True).all()
    assert decision_frame["full_shadow_audit_final_reason"].eq("score_below_min_edge_probability").all()
    assert decision_frame["decision_active"].eq(False).all()


def test_default_non_hmm_state_core_behavior_is_unchanged():
    feature_frame, label_frame = _feature_and_labels()
    probability_frame = _probability_feature_frame(feature_frame, horizon=3)
    decision_frame = objective_module.build_decision_frame(
        probability_frame,
        label_frame,
        params=extract_profile_defaults("state_core"),
        profile="state_core",
        playbook=None,
        horizon=3,
    )
    validation_frame = decision_frame.loc[decision_frame["temporal_segment"].astype(str) == "validation"].copy()
    result = evaluate_regime_prob_frame(validation_frame, config=_validation_config())

    assert "hmm_scoring_eligible" not in decision_frame.columns
    assert "hmm_oos_filtered_support_count" not in result.aggregate


def test_moe_router_objective_accepts_probability_feature_frame():
    feature_frame, label_frame = _feature_and_labels()
    probability_frame = _probability_feature_frame(feature_frame, horizon=3)
    objective = make_objective(
        probability_frame,
        label_frame,
        profile="moe_router",
        horizon=3,
        validation_config=_validation_config(),
    )

    score = objective(optuna.trial.FixedTrial(extract_profile_defaults("moe_router")))

    assert isinstance(score, float)


def test_state_core_objective_accepts_probability_feature_frame():
    feature_frame, label_frame = _feature_and_labels()
    probability_frame = _probability_feature_frame(feature_frame, horizon=3)
    objective = make_objective(
        probability_frame,
        label_frame,
        profile="state_core",
        horizon=3,
        validation_config=_validation_config(),
    )

    score = objective(optuna.trial.FixedTrial(extract_profile_defaults("state_core")))

    assert isinstance(score, float)


def test_transition_objective_accepts_probability_feature_frame():
    feature_frame, label_frame = _feature_and_labels()
    probability_frame = _probability_feature_frame(feature_frame, horizon=3)
    objective = make_objective(
        probability_frame,
        label_frame,
        profile="transition",
        horizon=3,
        validation_config=_validation_config(),
    )

    score = objective(optuna.trial.FixedTrial(extract_profile_defaults("transition")))

    assert isinstance(score, float)


def test_mtf_overlay_objective_accepts_context_frame():
    feature_frame, label_frame = _feature_and_labels()
    probability_frame = _probability_feature_frame(feature_frame, horizon=3)
    objective = make_objective(
        probability_frame,
        label_frame,
        profile="mtf_overlay",
        horizon=3,
        mtf_context_frame=_mtf_context_frame(probability_frame.index),
        validation_config=_validation_config(),
    )

    score = objective(optuna.trial.FixedTrial(extract_profile_defaults("mtf_overlay")))

    assert isinstance(score, float)


def test_external_context_objective_accepts_context_columns():
    feature_frame, label_frame = _feature_and_labels()
    context_frame = _external_context_feature_frame(feature_frame, horizon=3)
    objective = make_objective(
        context_frame,
        label_frame,
        profile="external_context",
        horizon=3,
        validation_config=_validation_config(),
    )

    score = objective(optuna.trial.FixedTrial(extract_profile_defaults("external_context")))

    assert isinstance(score, float)


def test_full_shadow_objective_accepts_context_and_mtf_frames():
    feature_frame, label_frame = _feature_and_labels()
    context_frame = _external_context_feature_frame(feature_frame, horizon=3)
    objective = make_objective(
        context_frame,
        label_frame,
        profile="full_shadow_only",
        horizon=3,
        mtf_context_frame=_mtf_context_frame(context_frame.index),
        validation_config=_validation_config(),
    )

    score = objective(optuna.trial.FixedTrial(extract_profile_defaults("full_shadow_only")))

    assert isinstance(score, float)


def test_run_study_returns_reviewable_audit_payload(tmp_path):
    feature_frame, label_frame = _feature_and_labels()
    result = run_study(
        feature_frame,
        label_frame,
        asset="BTCUSDT",
        timeframe="1h",
        profile="edge_calibration",
        playbook="trend_following",
        horizon=3,
        n_trials=2,
        validation_config=_validation_config(),
        storage=f"sqlite:///{tmp_path / 'regime_prob_v1_study.db'}",
        load_if_exists=True,
        seed=5,
        include_threshold_sweep=True,
    )

    assert result["model_name"] == "RegimeProbV1"
    assert result["profile"] == "edge_calibration"
    assert result["completed_trials"] == 2
    assert result["data"]["rows"] == len(feature_frame)
    assert "best_trial" in result
    assert "deploy_params" in result
    assert "oos" in result
    assert "baseline_oos" in result
    assert "promotion_gate" in result
    assert "threshold_sweep" in result
    assert "oos_gate_passed" in result["oos"]
    assert result["oos"]["deployed"] == result["promotion_gate"]["ready"]


def test_threshold_sweep_markdown_and_manifest_expansion():
    feature_frame, label_frame = _feature_and_labels()
    sweep = run_threshold_sweep(
        feature_frame,
        label_frame,
        extract_profile_defaults("edge_calibration"),
        profile="edge_calibration",
        playbook="trend_following",
        horizon=3,
        validation_config=_validation_config(),
        step=0.05,
        radius=1,
    )
    report = render_markdown_report(
        run_study(
            feature_frame,
            label_frame,
            asset="BTCUSDT",
            timeframe="1h",
            profile="edge_calibration",
            playbook="trend_following",
            horizon=3,
            n_trials=1,
            validation_config=_validation_config(),
            seed=7,
        )
    )
    runs = expand_manifest_runs(
        {
            "runs": [
                {"asset": "BTCUSDT", "timeframes": ["1h", "4h"], "profile": "edge_calibration", "playbook": "trend_following"}
            ]
        }
    )

    assert sweep["rows"]
    assert "RegimeProbV1 Optimization" in report
    assert len(runs) == 2
