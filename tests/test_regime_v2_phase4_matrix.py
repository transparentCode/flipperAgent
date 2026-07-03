from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_v2.evaluation import (
    HOLD_FOR_MORE_EVIDENCE,
    PROMOTE_TO_SHADOW_CANDIDATE,
    FailureDiagnosticConfig,
    Phase4DecisionConfig,
    Phase4OverlayMatrixConfig,
    diagnose_selection_overlay_failures,
    render_phase4_overlay_matrix_markdown,
    run_overlay_window_validation,
    run_phase4_overlay_matrix_from_frames,
    summarize_failure_diagnostics,
)
from libs.models.regime_v2.evaluation.overlay_validation import OverlayWindowValidationConfig
from libs.models.regime_v2.scripts.phase4_overlay_matrix_binance import _parse_args as parse_phase4_matrix_args


def _make_ohlcv(n: int = 180) -> pd.DataFrame:
    rng = np.random.default_rng(123)
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    returns = 0.003 + rng.normal(0.0, 0.001, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * 1.004
    low = np.minimum(open_, close) * 0.996
    volume = 1000.0 + rng.normal(0.0, 25.0, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def test_phase4_matrix_returns_hold_when_gate_is_too_strict() -> None:
    result = run_phase4_overlay_matrix_from_frames(
        {("BTCUSDT", "1h"): _make_ohlcv()},
        config=Phase4OverlayMatrixConfig(
            assets=("BTCUSDT",),
            timeframes=("1h",),
            horizon_bars_values=(4,),
            window_bars=80,
            step_bars=80,
            min_count=1,
            fee_bps_values=(0.0,),
            candidate_models=("Momentum", "TrendFollowing"),
            decision=Phase4DecisionConfig(
                min_valid_windows_per_fee=99,
                min_positive_rate=1.0,
                min_mean_lift=99.0,
                min_passed_combos=1,
                min_combo_pass_rate=1.0,
            ),
        ),
    )

    assert result["decision"] == HOLD_FOR_MORE_EVIDENCE
    assert result["summary"]["combo_count"] == 1
    assert result["summary"]["passed_combo_count"] == 0
    assert result["combos"][0]["passed"] is False
    assert result["combos"][0]["failure_reasons"]


def test_phase4_matrix_can_promote_when_thresholds_are_satisfied(monkeypatch) -> None:
    from libs.models.regime_v2.evaluation import phase4_matrix

    def fake_validation(*args, **kwargs):
        return {
            "summary": {
                "fee_summary": {
                    "0.0": {
                        "valid_window_count": 3,
                        "positive_gated_window_count": 2,
                        "positive_gated_rate": 0.67,
                        "mean_gated_lift": 0.012,
                        "median_gated_lift": 0.01,
                        "median_gated_win_rate": 0.6,
                    }
                }
            },
            "metrics": [{"window_id": 1, "fee_bps": 0.0, "gated_lift": 0.012}],
        }

    monkeypatch.setattr(phase4_matrix, "run_overlay_window_validation", fake_validation)

    result = run_phase4_overlay_matrix_from_frames(
        {("BTCUSDT", "1h"): _make_ohlcv()},
        config=Phase4OverlayMatrixConfig(
            assets=("BTCUSDT",),
            timeframes=("1h",),
            horizon_bars_values=(4,),
            window_bars=80,
            step_bars=80,
            min_count=1,
            fee_bps_values=(0.0,),
            candidate_models=("Momentum", "TrendFollowing"),
            decision=Phase4DecisionConfig(
                min_valid_windows_per_fee=1,
                min_positive_rate=0.5,
                min_mean_lift=0.0,
                min_passed_combos=1,
                min_combo_pass_rate=1.0,
            ),
        ),
    )

    assert result["decision"] == PROMOTE_TO_SHADOW_CANDIDATE
    assert result["summary"]["passed_combo_count"] == 1
    assert result["combos"][0]["passed"] is True
    assert result["window_metrics"]

    report = render_phase4_overlay_matrix_markdown(result)
    assert "RegimeV2 Phase 4 Overlay Validation Matrix" in report
    assert PROMOTE_TO_SHADOW_CANDIDATE in report
    assert "BTCUSDT" in report


def test_phase4_matrix_cli_args_parse() -> None:
    args = parse_phase4_matrix_args(
        [
            "--symbol",
            "BTCUSDT",
            "--timeframe",
            "4h",
            "--horizon-bars",
            "8",
            "--fee-bps",
            "7",
            "--min-positive-rate",
            "0.6",
            "--trend-score-floor",
            "0.2",
            "--breakout-score-floor",
            "0.18",
            "--mean-reversion-score-floor",
            "0.16",
            "--any-fee-can-pass",
        ]
    )

    assert "BTCUSDT" in args.symbol
    assert "4h" in args.timeframe
    assert 8 in args.horizon_bars
    assert 7.0 in args.fee_bps
    assert args.min_positive_rate == 0.6
    assert args.trend_score_floor == 0.2
    assert args.breakout_score_floor == 0.18
    assert args.mean_reversion_score_floor == 0.16
    assert args.any_fee_can_pass is True


def test_failure_diagnostics_explain_bad_aligned_pick() -> None:
    selected = pd.DataFrame(
        {
            "baseline_model": ["OtherModel", "Momentum"],
            "overlay_model": ["Momentum", "Momentum"],
            "baseline_edge": [0.02, 0.01],
            "overlay_edge": [-0.03, -0.02],
            "gated_edge": [-0.03, -0.02],
            "gated_direction": [1, 1],
            "overlay_direction": [1, 1],
            "_regime_side": [1, 1],
            "_overlay_aligned_boost": [True, True],
            "_overlay_conflict_penalty": [False, False],
            "regime_v2_policy_trend_score": [0.8, 0.2],
            "regime_v2_confidence": [0.8, 0.2],
            "regime_v2_uncertainty": [0.2, 0.8],
            "regime_v2_chop_risk": [0.1, 0.7],
            "regime_v2_false_breakout_risk": [0.1, 0.8],
            "regime_v2_shock_risk": [0.1, 0.1],
        }
    )

    diagnostics = diagnose_selection_overlay_failures(
        selected,
        config=FailureDiagnosticConfig(low_trend_score_threshold=0.35),
    )

    assert diagnostics["bad_row_count"] == 2
    assert diagnostics["reason_counts"]["aligned_pick_lost"] == 2
    assert diagnostics["reason_counts"]["trend_direction_wrong"] == 1
    assert diagnostics["reason_counts"]["low_trend_score"] == 1
    assert diagnostics["reason_counts"]["high_uncertainty"] == 1
    assert diagnostics["top_reasons"]

    aggregate = summarize_failure_diagnostics([diagnostics])
    assert aggregate["bad_row_count"] == 2
    assert aggregate["reason_counts"]["aligned_pick_lost"] == 2


def test_failure_diagnostics_are_playbook_aware() -> None:
    selected = pd.DataFrame(
        {
            "baseline_model": ["OtherModel", "OtherModel"],
            "overlay_model": ["SqueezeBreakout", "RegimePullbackScorer"],
            "baseline_edge": [0.01, 0.01],
            "overlay_edge": [-0.02, -0.03],
            "gated_edge": [-0.02, -0.03],
            "gated_direction": [1, -1],
            "overlay_direction": [1, -1],
            "_regime_side": [1, 0],
            "_overlay_playbook": ["breakout", "mean_reversion"],
            "_overlay_aligned_boost": [True, True],
            "_overlay_conflict_penalty": [False, False],
            "regime_v2_policy_trend_score": [0.0, 0.0],
            "regime_v2_policy_breakout_score": [0.2, 0.8],
            "regime_v2_policy_mean_reversion_score": [0.8, 0.2],
            "regime_v2_confidence": [0.8, 0.8],
            "regime_v2_uncertainty": [0.2, 0.2],
            "regime_v2_chop_risk": [0.1, 0.1],
            "regime_v2_false_breakout_risk": [0.1, 0.1],
            "regime_v2_shock_risk": [0.1, 0.1],
        }
    )

    diagnostics = diagnose_selection_overlay_failures(
        selected,
        config=FailureDiagnosticConfig(low_trend_score_threshold=0.35),
    )

    assert diagnostics["bad_row_count"] == 2
    assert diagnostics["reason_counts"]["low_trend_score"] == 0
    assert diagnostics["reason_counts"]["low_breakout_score"] == 1
    assert diagnostics["reason_counts"]["low_mean_reversion_score"] == 1
    assert diagnostics["reason_counts"]["aligned_pick_lost"] == 2


def test_overlay_window_validation_accepts_trendline_family() -> None:
    ohlcv = _make_ohlcv()
    ohlcv["trendline_direction"] = 1
    ohlcv["trendline_score"] = 0.8

    result = run_overlay_window_validation(
        ohlcv,
        asset="BTCUSDT",
        timeframe="1h",
        config=OverlayWindowValidationConfig(
            horizon_bars=4,
            window_bars=80,
            step_bars=80,
            min_count=1,
            fee_bps_values=(0.0,),
            candidate_models=("Trendline",),
        ),
    )

    assert result["metrics"][0]["candidate_counts"] == {"Trendline": 80}
    assert result["summary"]["candidate_models"] == ["Trendline"]


def test_overlay_window_validation_includes_failure_diagnostics() -> None:
    result = run_overlay_window_validation(
        _make_ohlcv(),
        asset="BTCUSDT",
        timeframe="1h",
        config=OverlayWindowValidationConfig(
            horizon_bars=4,
            window_bars=80,
            step_bars=80,
            min_count=1,
            fee_bps_values=(0.0,),
            candidate_models=("Momentum", "TrendFollowing"),
        ),
    )

    assert "failure_diagnostics" in result["summary"]
    assert "failure_diagnostics" in result["summary"]["fee_summary"]["0.0"]
    assert "failure_diagnostics" in result["metrics"][0]
    assert "reason_counts" in result["metrics"][0]["failure_diagnostics"]
