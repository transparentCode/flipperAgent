from __future__ import annotations

from libs.regime.optimization.candidate_promotion import build_candidate_promotion_report


def test_candidate_promotion_report_prefers_overlay_when_score_and_ic_improve():
    breadth_rows = [
        {
            "asset": "BTCUSDT",
            "timeframe": "1h",
            "hmm_health": {
                "walk_forward": {
                    "passed": False,
                    "unstable_fit_rate": 0.12,
                }
            },
            "breadth_variants": {
                "walk_forward": {
                    "regime_only": {
                        "score": 0.50,
                        "benchmarks": {
                            "forward_return_ic": -0.10,
                            "sharpe_improvement": 1.0,
                            "passed_strict_baseline_gate": False,
                            "avg_regime_duration": 12.0,
                            "flip_flop_rate": 0.08,
                        },
                    },
                    "breadth_gate": {
                        "score": 0.51,
                        "benchmarks": {
                            "forward_return_ic": -0.09,
                            "sharpe_improvement": 1.5,
                            "passed_strict_baseline_gate": False,
                            "avg_regime_duration": 12.0,
                            "flip_flop_rate": 0.08,
                        },
                    },
                    "breadth_blend": {
                        "score": 0.70,
                        "benchmarks": {
                            "forward_return_ic": -0.04,
                            "sharpe_improvement": 3.0,
                            "passed_strict_baseline_gate": False,
                            "avg_regime_duration": 11.0,
                            "flip_flop_rate": 0.09,
                        },
                    },
                },
                "full_sample": {},
            },
        },
        {
            "asset": "ETHUSDT",
            "timeframe": "1h",
            "hmm_health": {
                "walk_forward": {
                    "passed": False,
                    "unstable_fit_rate": 0.12,
                }
            },
            "breadth_variants": {
                "walk_forward": {
                    "regime_only": {
                        "score": 0.48,
                        "benchmarks": {
                            "forward_return_ic": -0.08,
                            "sharpe_improvement": 1.2,
                            "passed_strict_baseline_gate": False,
                            "avg_regime_duration": 10.0,
                            "flip_flop_rate": 0.09,
                        },
                    },
                    "breadth_gate": {
                        "score": 0.49,
                        "benchmarks": {
                            "forward_return_ic": -0.08,
                            "sharpe_improvement": 1.3,
                            "passed_strict_baseline_gate": False,
                            "avg_regime_duration": 10.0,
                            "flip_flop_rate": 0.09,
                        },
                    },
                    "breadth_blend": {
                        "score": 0.69,
                        "benchmarks": {
                            "forward_return_ic": -0.03,
                            "sharpe_improvement": 3.2,
                            "passed_strict_baseline_gate": False,
                            "avg_regime_duration": 9.0,
                            "flip_flop_rate": 0.10,
                        },
                    },
                },
                "full_sample": {},
            },
        },
    ]
    hmm_rows = [
        {
            "asset": "BTCUSDT",
            "timeframe": "1h",
            "best_variant": "fixed3_full",
            "hmm_variants": {
                "fixed3_full": {
                    "mean_fold_score": 0.60,
                    "walk_forward": {
                        "forward_return_ic": -0.12,
                        "sharpe_improvement": 2.5,
                        "passed_strict_baseline_gate": False,
                        "avg_regime_duration": 4.0,
                        "flip_flop_rate": 0.20,
                    },
                    "full_sample": {},
                    "hmm_health": {"walk_forward": {"passed": False, "unstable_fit_rate": 0.50}},
                }
            },
        },
        {
            "asset": "ETHUSDT",
            "timeframe": "1h",
            "best_variant": "current",
            "hmm_variants": {
                "current": {
                    "mean_fold_score": 0.47,
                    "walk_forward": {
                        "forward_return_ic": -0.09,
                        "sharpe_improvement": 1.8,
                        "passed_strict_baseline_gate": False,
                        "avg_regime_duration": 4.0,
                        "flip_flop_rate": 0.20,
                    },
                    "full_sample": {},
                    "hmm_health": {"walk_forward": {"passed": False, "unstable_fit_rate": 0.45}},
                }
            },
        },
    ]

    report = build_candidate_promotion_report(breadth_rows, hmm_rows)

    assert report["panel_ranking"][0]["candidate"] == "breadth_blend"
    assert report["panel_summary"]["breadth_blend"]["promotion_decision"] == "hold_for_overlay_only"
    assert report["panel_summary"]["best_hmm_preset"]["promotion_decision"] == "reject"


def test_candidate_promotion_can_promote_when_strict_and_ic_improve():
    breadth_rows = [
        {
            "asset": "BTCUSDT",
            "timeframe": "30m",
            "hmm_health": {"walk_forward": {"passed": False, "unstable_fit_rate": 0.10}},
            "breadth_variants": {
                "walk_forward": {
                    "regime_only": {
                        "score": 0.55,
                        "benchmarks": {
                            "forward_return_ic": -0.02,
                            "sharpe_improvement": 1.0,
                            "passed_strict_baseline_gate": False,
                            "avg_regime_duration": 8.0,
                            "flip_flop_rate": 0.10,
                        },
                    },
                    "breadth_blend": {
                        "score": 0.75,
                        "benchmarks": {
                            "forward_return_ic": 0.02,
                            "sharpe_improvement": 4.0,
                            "passed_strict_baseline_gate": True,
                            "avg_regime_duration": 8.0,
                            "flip_flop_rate": 0.10,
                        },
                    },
                },
                "full_sample": {},
            },
        }
    ]
    hmm_rows = []

    report = build_candidate_promotion_report(breadth_rows, hmm_rows, candidate_names=("regime_only", "breadth_blend"))

    assert report["panel_summary"]["breadth_blend"]["promotion_decision"] == "promote"
