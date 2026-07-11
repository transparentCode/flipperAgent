from __future__ import annotations

import numpy as np
import optuna
import pandas as pd

from libs.models.regime_v2.optimization import extract_profile_defaults
from libs.models.regime_v2.optimization.optimizer import (
    evaluate_oos,
    format_deploy_params,
    make_objective,
    post_process_params,
)
from libs.models.regime_v2.optimization.batch_optimize import expand_manifest_runs, run_manifest
from libs.models.regime_v2.optimization.optimize import (
    _coerce_time_ms,
    _limit_for_range,
    _normalize_ohlcv,
    _parse_args,
    run_study,
)
from libs.models.regime_v2.optimization.reports import render_markdown_report
from libs.models.regime_v2.optimization.threshold_sweep import run_threshold_sweep
from libs.models.regime_v2.optimization.validation import (
    RegimeV2OptimizationGates,
    RegimeV2RollingValidationConfig,
    evaluate_regime_v2_frame,
)


def _make_ohlcv(n: int = 180) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    returns = 0.002 + rng.normal(0.0, 0.0008, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * 1.003
    low = np.minimum(open_, close) * 0.997
    volume = 1000.0 + rng.normal(0.0, 20.0, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def _comparison_frame(n: int = 80, *, active_count: int = 24) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    active = np.zeros(n, dtype=bool)
    active[:active_count] = True
    fwd = np.where(active, 0.03, -0.005)
    return pd.DataFrame(
        {
            "close": np.linspace(100.0, 110.0, n),
            "fwd_return": fwd,
            "fwd_abs_return": np.abs(fwd),
            "regime_v2_summary_label": "bull_trend",
            "regime_v2_trend_direction": "bull",
            "regime_v2_policy_allow_trend_following": active,
            "regime_v2_policy_allow_breakout": False,
            "regime_v2_policy_allow_mean_reversion": False,
            "regime_v2_policy_allow_scalping": False,
            "regime_v2_policy_allow_countertrend": False,
            "regime_v2_policy_max_position_scale": active.astype(float),
            "regime_v2_policy_trend_score": np.where(active, 0.8, 0.0),
        },
        index=idx,
    )


def _validation_config() -> RegimeV2RollingValidationConfig:
    return RegimeV2RollingValidationConfig(
        window_bars=80,
        step_bars=40,
        min_window_bars=40,
        gates=RegimeV2OptimizationGates(
            min_support_count=10,
            min_support_rate=0.05,
            max_flip_rate=0.20,
            max_policy_turnover=0.20,
            min_oos_score_ratio=0.25,
        ),
    )


def test_validation_scores_supported_positive_lift_frame():
    result = evaluate_regime_v2_frame(_comparison_frame(), config=_validation_config())

    assert result.rejected is False
    assert result.score > 0.0
    assert result.aggregate["positive_window_rate"] == 1.0
    assert result.aggregate["mean_support_count"] >= 10


def test_validation_rejects_low_support_frame():
    result = evaluate_regime_v2_frame(_comparison_frame(active_count=2), config=_validation_config())

    assert result.rejected is True
    assert "support_count_below_minimum" in result.rejection_reasons


def test_make_objective_accepts_fixed_trial_and_records_metrics():
    defaults = extract_profile_defaults("1h", profile="core")
    objective = make_objective(
        _make_ohlcv(),
        asset="BTCUSDT",
        timeframe="1h",
        profile="core",
        horizon_bars=4,
        validation_config=RegimeV2RollingValidationConfig(
            window_bars=24,
            step_bars=12,
            min_window_bars=20,
            gates=RegimeV2OptimizationGates(
                min_support_count=1,
                min_support_rate=0.0,
                max_flip_rate=1.0,
                max_policy_turnover=1.0,
            ),
        ),
        purge_bars=5,
    )
    trial = optuna.trial.FixedTrial(defaults)

    score = objective(trial)

    assert isinstance(score, float)
    assert "regime_v2_validation" in trial.user_attrs


def test_evaluate_oos_and_deploy_format_use_dotted_overrides():
    params = {
        "trend.fast_ema": 14.2,
        "fusion.trend_threshold": 0.55,
    }

    processed = post_process_params(params, timeframe="1h", profile="core")
    deploy = format_deploy_params(params, timeframe="1h", profile="core")
    result = evaluate_oos(
        _make_ohlcv(),
        processed,
        asset="BTCUSDT",
        timeframe="1h",
        profile="core",
        horizon_bars=4,
        validation_config=RegimeV2RollingValidationConfig(
            window_bars=24,
            step_bars=12,
            min_window_bars=20,
            gates=RegimeV2OptimizationGates(
                min_support_count=1,
                min_support_rate=0.0,
                max_flip_rate=1.0,
                max_policy_turnover=1.0,
            ),
        ),
        purge_bars=5,
    )

    assert processed["trend.fast_ema"] == 14
    assert deploy["params"]["fusion.trend_threshold"] == 0.55
    assert set(result) >= {"train", "validate", "oos", "deployed", "params"}


def test_optimize_cli_args_default_to_core_profile():
    args = _parse_args(
        [
            "--asset",
            "BTCUSDT",
            "--timeframe",
            "1h",
            "--since",
            "2021-01-01",
            "--until",
            "2024-12-31",
        ]
    )

    assert args.asset == "BTCUSDT"
    assert args.timeframe == "1h"
    assert args.profile == "core"
    assert args.n_trials is None
    assert args.since == "2021-01-01"
    assert args.until == "2024-12-31"
    assert args.storage is None
    assert args.resume is False
    assert args.threshold_sweep is False


def test_date_cutoff_helpers_accept_iso_dates_and_ms():
    since = _coerce_time_ms("2021-01-01")
    until = _coerce_time_ms("2021-01-03")

    assert since == 1609459200000
    assert until == 1609632000000
    assert _coerce_time_ms("1609459200000") == 1609459200000
    assert _limit_for_range("1h", since_ms=since, until_ms=until, days=1) == 100


def test_normalize_ohlcv_accepts_iso_timestamp_column():
    raw = pd.DataFrame(
        {
            "timestamp": ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"],
            "open": ["100", "100.5"],
            "high": ["101", "102"],
            "low": ["99", "100"],
            "close": ["100.5", "101"],
            "volume": ["1000", "1100"],
        }
    )

    normalized = _normalize_ohlcv(raw)

    assert list(normalized.columns) == ["open", "high", "low", "close", "volume"]
    assert str(normalized.index.tz) == "UTC"
    assert normalized.iloc[0]["close"] == 100.5


def test_run_study_returns_reviewable_audit_payload(tmp_path):
    result = run_study(
        _make_ohlcv(),
        asset="BTCUSDT",
        timeframe="1h",
        profile="core",
        n_trials=2,
        horizon_bars=4,
        validation_config=RegimeV2RollingValidationConfig(
            window_bars=24,
            step_bars=12,
            min_window_bars=20,
            gates=RegimeV2OptimizationGates(
                min_support_count=1,
                min_support_rate=0.0,
                max_flip_rate=1.0,
                max_policy_turnover=1.0,
            ),
        ),
        purge_bars=5,
        seed=3,
        storage=f"sqlite:///{tmp_path / 'regime_v2_study.db'}",
        load_if_exists=True,
    )

    assert result["model_name"] == "RegimeV2"
    assert result["profile"] == "core"
    assert result["completed_trials"] == 2
    assert result["storage"].startswith("sqlite:///")
    assert result["data"]["rows"] == 180
    assert "best_trial" in result
    assert "deploy_params" in result
    assert "oos" in result
    assert "baseline_oos" in result
    assert "default_vs_tuned" in result


def test_markdown_report_includes_baseline_delta():
    result = run_study(
        _make_ohlcv(),
        asset="BTCUSDT",
        timeframe="1h",
        profile="core",
        n_trials=1,
        horizon_bars=4,
        validation_config=RegimeV2RollingValidationConfig(
            window_bars=24,
            step_bars=12,
            min_window_bars=20,
            gates=RegimeV2OptimizationGates(
                min_support_count=1,
                min_support_rate=0.0,
                max_flip_rate=1.0,
                max_policy_turnover=1.0,
            ),
        ),
        purge_bars=5,
        seed=4,
    )

    markdown = render_markdown_report(result)

    assert "# RegimeV2 Optimization: BTCUSDT 1h" in markdown
    assert "Default Vs Tuned" in markdown
    assert "Deploy Params" in markdown


def test_threshold_sweep_returns_review_rows():
    base_params = {
        "fusion.trend_threshold": 0.50,
        "policy.min_confidence": 0.35,
    }

    result = run_threshold_sweep(
        _make_ohlcv(),
        base_params,
        asset="BTCUSDT",
        timeframe="1h",
        profile="core",
        horizon_bars=4,
        validation_config=RegimeV2RollingValidationConfig(
            window_bars=24,
            step_bars=12,
            min_window_bars=20,
            gates=RegimeV2OptimizationGates(
                min_support_count=1,
                min_support_rate=0.0,
                max_flip_rate=1.0,
                max_policy_turnover=1.0,
            ),
        ),
        purge_bars=5,
        params=("fusion.trend_threshold",),
        radius=0,
    )

    assert result["params"] == ["fusion.trend_threshold"]
    assert len(result["rows"]) == 1
    assert result["rows"][0]["param"] == "fusion.trend_threshold"


def test_batch_manifest_expands_and_runs_local_csv(tmp_path):
    csv_path = tmp_path / "ohlcv.csv"
    _make_ohlcv().reset_index(names="timestamp").to_csv(csv_path, index=False)
    manifest = {
        "defaults": {
            "profile": "core",
            "n_trials": 1,
            "horizon_bars": 4,
            "purge_bars": 5,
            "window_bars": 24,
            "step_bars": 12,
            "min_window_bars": 20,
            "min_support_count": 1,
            "min_support_rate": 0.0,
            "max_flip_rate": 1.0,
            "max_policy_turnover": 1.0,
            "skip_baseline": True,
        },
        "runs": [
            {
                "asset": "BTCUSDT",
                "timeframes": ["1h"],
                "input_csv": str(csv_path),
                "until": "2024-12-31",
            }
        ],
    }

    expanded = expand_manifest_runs(manifest)
    report = run_manifest(manifest, output_dir=tmp_path / "out")

    assert expanded == [
        {
            "asset": "BTCUSDT",
            "timeframe": "1h",
            "input_csv": str(csv_path),
            "until": "2024-12-31",
        }
    ]
    assert report["completed_runs"] == 1
    assert report["runs"][0]["asset"] == "BTCUSDT"
    assert (tmp_path / "out" / "RegimeV2_BTCUSDT_1h_core.json").exists()
