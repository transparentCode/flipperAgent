from __future__ import annotations

from libs.regime.scripts.evaluate_current_regime import (
    HMM_VARIANT_PRESETS,
    _hmm_health_from_metrics,
    _params_for_hmm_variant,
    _rank_hmm_variants,
)


def test_params_for_hmm_variant_applies_expected_overrides():
    base = {
        "hmm_n_states": 0,
        "hmm_covariance_type": "full",
        "hmm_robust_scoring": True,
        "other": 7,
    }

    params = _params_for_hmm_variant(base, "fixed2_diag")

    assert params["hmm_n_states"] == 2
    assert params["hmm_covariance_type"] == "diag"
    assert params["hmm_robust_scoring"] is False
    assert params["other"] == 7


def test_hmm_health_gate_requires_all_thresholds():
    good = _hmm_health_from_metrics(
        {
            "hmm_fit_failure_rate": 0.04,
            "hmm_unstable_fit_rate": 0.10,
            "hmm_zero_transition_fit_rate": 0.01,
        },
        has_data=True,
    )
    bad = _hmm_health_from_metrics(
        {
            "hmm_fit_failure_rate": 0.04,
            "hmm_unstable_fit_rate": 0.20,
            "hmm_zero_transition_fit_rate": 0.01,
        },
        has_data=True,
    )

    assert good["passed"] is True
    assert bad["passed"] is False


def test_hmm_health_gate_rejects_missing_walk_forward_data():
    no_data = _hmm_health_from_metrics(
        {
            "hmm_fit_failure_rate": 0.0,
            "hmm_unstable_fit_rate": 0.0,
            "hmm_zero_transition_fit_rate": 0.0,
        },
        has_data=False,
    )

    assert no_data["passed"] is False
    assert no_data["has_data"] is False


def test_rank_hmm_variants_prioritizes_health_then_score():
    rows = [
        {
            "variant": "high_score_unhealthy",
            "mean_fold_score": 0.9,
            "strict_pass": False,
            "hmm_health_pass": False,
            "has_walk_forward_data": True,
        },
        {
            "variant": "healthy_lower_score",
            "mean_fold_score": 0.4,
            "strict_pass": False,
            "hmm_health_pass": True,
            "has_walk_forward_data": True,
        },
        {
            "variant": "strict_and_healthy",
            "mean_fold_score": 0.3,
            "strict_pass": True,
            "hmm_health_pass": True,
            "has_walk_forward_data": True,
        },
    ]

    ranked = _rank_hmm_variants(rows)

    assert ranked[0]["variant"] == "strict_and_healthy"
    assert ranked[1]["variant"] == "healthy_lower_score"
    assert ranked[2]["variant"] == "high_score_unhealthy"


def test_all_expected_hmm_presets_are_available():
    assert {
        "current",
        "fixed2_diag",
        "fixed2_full",
        "fixed3_diag",
        "fixed3_full",
    }.issubset(HMM_VARIANT_PRESETS.keys())


def test_rank_hmm_variants_penalizes_missing_walk_forward_data():
    rows = [
        {
            "variant": "no_data",
            "mean_fold_score": None,
            "strict_pass": False,
            "hmm_health_pass": False,
            "has_walk_forward_data": False,
        },
        {
            "variant": "with_data",
            "mean_fold_score": 0.1,
            "strict_pass": False,
            "hmm_health_pass": False,
            "has_walk_forward_data": True,
        },
    ]

    ranked = _rank_hmm_variants(rows)

    assert ranked[0]["variant"] == "with_data"
