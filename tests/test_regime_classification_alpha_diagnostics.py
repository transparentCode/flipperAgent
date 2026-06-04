"""Tests for RegimeClassification alpha artifact diagnostics."""

from __future__ import annotations

from libs.models.regime_classification.optimization.diagnostics import (
    diagnose_alpha_payload,
)
from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)


def _overlay(policy_kind: str, decision: str, sharpe: float, shuffled: float):
    return {
        "metrics": {
            "oos": {
                "sharpe": sharpe,
                "calmar": max(sharpe, 0) / 2,
                "total_return": max(sharpe, 0) / 100,
                "avg_position": 0.2,
                "turnover": 0.1,
            }
        },
        "shuffled_control": {
            "oos": {
                "sharpe": shuffled,
                "calmar": shuffled / 2,
                "total_return": shuffled / 100,
            }
        },
        "oos_lifts": {
            "sharpe_vs_baseline": sharpe - 0.1,
            "calmar_vs_baseline": max(sharpe, 0) / 3,
            "total_return_vs_baseline": max(sharpe, 0) / 100,
            "sharpe_vs_shuffled": sharpe - shuffled,
            "calmar_vs_shuffled": max(sharpe, 0) / 2 - shuffled / 2,
        },
        "decision": decision,
        "selection": {
            "validation_score": 1.0 + sharpe,
            "policy": {
                "policy_kind": policy_kind,
                "max_vol_percentile": 80.0,
                "max_changepoint_prob": 0.5,
                "max_crisis_prob": 0.5,
                "min_trend_strength": 0.2,
                "min_confidence": 0.7,
                "trend_power": 1.5,
                "min_position_scale": 0.1,
            },
        },
    }


def _strategy(policy_kind: str, decision: str, sharpe: float, shuffled: float):
    return {
        "baseline": {"oos": {"sharpe": 0.1}},
        "overlays": {
            "optimized_policy": _overlay(policy_kind, decision, sharpe, shuffled)
        },
        "ranking": [],
    }


def test_diagnose_alpha_payload_reports_policy_and_shuffled_stats():
    payload = {
        "panel_summary": {"usable_slices": 1},
        "reports": [
            {
                "asset": "BNBUSDT",
                "timeframe": "30m",
                "status": "ok",
                "folds": [
                    {
                        "fold_index": 0,
                        "strategies": {
                            "buy_and_hold": _strategy(
                                "confidence_scaled",
                                "promote_to_downstream_research",
                                1.5,
                                -0.5,
                            )
                        },
                    },
                    {
                        "fold_index": 1,
                        "strategies": {
                            "sma_cross": _strategy("trend_scaled", "reject", -1.0, -2.0)
                        },
                    },
                ],
            }
        ],
    }

    result = diagnose_alpha_payload(
        payload,
        settings=load_regime_optimization_settings(),
    )
    report = result["reports"][0]

    assert report["folds"] == 2
    assert report["policy_stability"]["best_policy_kind_counts"] == {
        "confidence_scaled": 1,
        "trend_scaled": 1,
    }
    assert report["shuffled_control"]["best_rows"]["real_beats_shuffled_rate"] == 1.0
    assert "oos_sharpe_low" in report["gate_failures"]["failure_counts"]
