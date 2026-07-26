from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from libs.models.regime_v2 import RegimeV2Orchestrator
from libs.models.regime_v2.adapters import RegimeV2FeatureProducer
from libs.models.regime_v2.config import PolicyConfig, timeframe_scaled_config
from libs.models.regime_v2.evaluation import (
    DownstreamAblationConfig,
    RegimeComparisonConfig,
    OverlayWindowValidationConfig,
    RegimeV2TrendOverlayConfig,
    TrendCandidateExportConfig,
    TrendFamilyAblationConfig,
    build_standard_feature_frame,
    export_builtin_trend_candidates,
    run_downstream_ablation,
    run_overlay_window_validation,
    run_regime_comparison,
    run_regime_v2_trend_selection_overlay,
    run_trend_family_ablation,
)
from libs.models.regime_v2.scripts.ablate_binance_native import _parse_args as parse_ablation_args
from libs.models.regime_v2.scripts.ablate_builtin_trend_models_binance import _parse_args as parse_builtin_trend_args
from libs.models.regime_v2.scripts.ablate_trend_family import _parse_args as parse_trend_family_args
from libs.models.regime_v2.scripts.validate_builtin_trend_overlay_binance import _parse_args as parse_overlay_validation_args
from libs.models.regime_v2.scripts.compare_binance_native import (
    fetch_binance_native_ohlcv,
    normalize_binance_native_ohlcv,
)
from libs.models.regime_v2.contracts import RegimeEvidence, RegimePolicy, RegimeV2Output
from libs.models.regime_v2.data_quality import validate_ohlcv
from libs.models.regime_v2.policy import evidence_to_policy


def _make_ohlcv(n: int = 260, *, trend: float = 0.003, noise: float = 0.001) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    returns = trend + rng.normal(0.0, noise, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * 1.004
    low = np.minimum(open_, close) * 0.996
    volume = 1000.0 + rng.normal(0.0, 25.0, n).clip(-100.0, 100.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=idx,
    )


def _make_range_ohlcv(n: int = 260) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    oscillation = np.sin(np.linspace(0, 18 * np.pi, n)) * 0.03
    close = 100.0 * (1.0 + oscillation + rng.normal(0.0, 0.004, n))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * 1.003
    low = np.minimum(open_, close) * 0.997
    volume = 1000.0 + rng.normal(0.0, 20.0, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def _make_shock_ohlcv(n: int = 260) -> pd.DataFrame:
    rng = np.random.default_rng(17)
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    returns = rng.normal(0.0, 0.001, n)
    returns[-1] = 0.08
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * 1.003
    low = np.minimum(open_, close) * 0.997
    volume = 1000.0 + rng.normal(0.0, 20.0, n)
    volume[-1] = 2500.0
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


class TestRegimeV2Contracts:
    def test_output_contract_to_dict(self):
        evidence = RegimeEvidence(
            timestamp=1,
            asset="BTCUSDT",
            timeframe="1h",
            trend_direction="bull",
            trend_strength=0.7,
            trend_persistence=0.6,
            trend_confidence=0.65,
            volatility_percentile=55.0,
            volatility_state="normal",
            compression_score=0.2,
            shock_risk=0.1,
            mean_reversion_score=0.2,
            range_quality=0.3,
            chop_risk=0.2,
            structural_break_risk=0.1,
            breakout_quality=0.4,
            false_breakout_risk=0.2,
            market_context_score=0.1,
            breadth_confirmation=0.1,
            liquidity_stress=0.0,
            confidence=0.6,
            uncertainty=0.4,
            summary_label="bull_trend",
        )
        policy = RegimePolicy(
            allow_trend_following=True,
            allow_breakout=False,
            allow_mean_reversion=False,
            allow_scalping=True,
            allow_countertrend=False,
            max_position_scale=0.5,
            stop_multiplier=1.2,
            target_multiplier=1.3,
            holding_period_prior=12,
        )
        output = RegimeV2Output(
            evidence=evidence,
            policy=policy,
            data_quality=RegimeV2Orchestrator.create("BTCUSDT", "1h").analyze(_make_ohlcv()).data_quality,
        )
        as_dict = output.to_dict()
        assert as_dict["evidence"]["summary_label"] == "bull_trend"
        assert as_dict["policy"]["allow_trend_following"] is True
        assert "data_quality" in as_dict


class TestRegimeV2DataQuality:
    def test_quality_report_detects_missing_fields(self):
        df = _make_ohlcv().drop(columns=["volume"])
        cfg = timeframe_scaled_config("1h").data_quality
        report = validate_ohlcv(df, cfg)
        assert report.usable is False
        assert report.missing_required_fields == ("volume",)
        assert "missing_required_fields" in report.reasons

    def test_short_history_is_warmup_incomplete(self):
        cfg = timeframe_scaled_config("1h").data_quality
        report = validate_ohlcv(_make_ohlcv(20), cfg)
        assert report.rows == 20
        assert report.warmup_complete is False
        assert "insufficient_history" in report.reasons


class TestRegimeV2Orchestrator:
    def test_analyze_series_outputs_evidence_and_policy_columns(self):
        orch = RegimeV2Orchestrator.create("BTCUSDT", "1h")
        result = orch.analyze_series(_make_ohlcv())

        required = {
            "summary_label",
            "trend_strength",
            "trend_direction",
            "volatility_percentile",
            "mean_reversion_score",
            "structural_break_risk",
            "breakout_quality",
            "pre_breakout_setup_score",
            "displacement_breakout_score",
            "post_breakout_retest_score",
            "confidence",
            "uncertainty",
            "policy_allow_trend_following",
            "policy_max_position_scale",
        }
        assert required.issubset(result.columns)
        score_columns = {
            "policy_trend_score",
            "policy_breakout_score",
            "policy_mean_reversion_score",
            "policy_scalping_score",
            "policy_countertrend_score",
            "policy_breakout_setup_score",
            "policy_displacement_breakout_score",
            "policy_retest_breakout_score",
        }
        assert score_columns.issubset(result.columns)
        assert len(result) == 260
        assert result["confidence"].between(0.0, 1.0).all()
        assert result["uncertainty"].between(0.0, 1.0).all()
        assert result["volatility_percentile"].between(0.0, 100.0).all()
        for column in score_columns:
            assert result[column].between(0.0, 1.0).all()

    def test_analyze_latest_matches_analyze_series_last_row(self):
        df = _make_ohlcv()
        orch = RegimeV2Orchestrator.create("BTCUSDT", "1h")
        series_last = orch.analyze_series(df).iloc[-1]
        snapshot = orch.analyze(df)

        assert snapshot.evidence.summary_label == series_last["summary_label"]
        assert snapshot.evidence.trend_direction == series_last["trend_direction"]
        assert snapshot.evidence.confidence == series_last["confidence"]
        assert snapshot.policy.max_position_scale == series_last["policy_max_position_scale"]

    def test_analyze_series_marks_early_rows_as_warming_up(self):
        orch = RegimeV2Orchestrator.create("BTCUSDT", "1h")
        df = _make_ohlcv(130, trend=0.0015, noise=0.0001)

        result = orch.analyze_series(df)

        assert result.iloc[0]["summary_label"] == "warming_up"
        assert result.iloc[0]["uncertainty"] == 1.0
        assert result.iloc[0]["confidence"] < 0.2
        assert result.iloc[118]["summary_label"] == "warming_up"
        assert result.iloc[119]["summary_label"] != "warming_up"

    def test_duplicate_final_timestamp_does_not_retroactively_degrade_history(self):
        orch = RegimeV2Orchestrator.create("BTCUSDT", "1h")
        df = _make_ohlcv(130, trend=0.0015, noise=0.0001)
        duplicated = pd.concat([df, df.iloc[[-1]]])

        result = orch.analyze_series(duplicated)

        assert len(result) == len(df)
        assert result.iloc[0]["summary_label"] == "warming_up"
        assert "data_quality_degraded" not in set(result["summary_label"].iloc[:120])
        assert result.iloc[-1]["summary_label"] != "data_quality_degraded"

    def test_short_history_returns_warming_up_snapshot(self):
        orch = RegimeV2Orchestrator.create("ETHUSDT", "1h")
        snapshot = orch.analyze(_make_ohlcv(20))
        assert snapshot.evidence.summary_label == "warming_up"
        assert snapshot.evidence.confidence == 0.0 or snapshot.evidence.confidence < 0.15
        assert snapshot.evidence.uncertainty == 1.0
        assert snapshot.policy.max_position_scale == 0.0

    def test_market_context_columns_are_consumed_when_present(self):
        df = _make_ohlcv()
        df["eng_regime_alignment_score"] = 0.8
        df["eng_market_cap_breadth"] = 0.05
        df["eng_cross_asset_regime_state"] = 1

        orch = RegimeV2Orchestrator.create("SOLUSDT", "1h")
        result = orch.analyze_series(df)
        assert result["market_context_score"].iloc[-1] > 0.0
        assert result["breadth_confirmation"].iloc[-1] > 0.0

    def test_clean_bull_trend_allows_trend_playbook(self):
        orch = RegimeV2Orchestrator.create("BTCUSDT", "1h")
        snapshot = orch.analyze(_make_ohlcv(trend=0.003, noise=0.001))

        assert snapshot.evidence.summary_label == "bull_trend"
        assert snapshot.evidence.trend_direction == "bull"
        assert snapshot.evidence.trend_strength > 0.70
        assert snapshot.evidence.chop_risk < 0.55
        assert snapshot.policy.allow_trend_following is True
        assert snapshot.policy.trend_score > 0.0
        assert snapshot.policy.max_position_scale > 0.0

    def test_clean_bear_trend_allows_trend_playbook(self):
        orch = RegimeV2Orchestrator.create("BTCUSDT", "1h")
        snapshot = orch.analyze(_make_ohlcv(trend=-0.003, noise=0.001))

        assert snapshot.evidence.summary_label == "bear_trend"
        assert snapshot.evidence.trend_direction == "bear"
        assert snapshot.evidence.trend_strength > 0.70
        assert snapshot.policy.allow_trend_following is True

    def test_direction_deadzone_override_can_suppress_trend_label(self):
        df = _make_ohlcv(trend=0.003, noise=0.001)

        baseline = RegimeV2Orchestrator.create("BTCUSDT", "1h").analyze(df)
        overridden = RegimeV2Orchestrator.create(
            "BTCUSDT",
            "1h",
            **{"trend.direction_deadzone": 0.99},
        ).analyze(df)

        assert baseline.evidence.summary_label == "bull_trend"
        assert baseline.evidence.trend_direction == "bull"
        assert overridden.evidence.trend_strength == pytest.approx(baseline.evidence.trend_strength)
        assert overridden.evidence.trend_direction == "neutral"
        assert overridden.evidence.summary_label == "neutral"
        assert overridden.policy.allow_trend_following is False

    def test_range_scenario_is_not_promoted_to_trend(self):
        orch = RegimeV2Orchestrator.create("BTCUSDT", "1h")
        snapshot = orch.analyze(_make_range_ohlcv())

        assert snapshot.evidence.summary_label in {"choppy", "compressed_range", "mean_reversion_range", "neutral"}
        assert snapshot.evidence.trend_strength < 0.45
        assert snapshot.policy.allow_trend_following is False

    def test_shock_scenario_blocks_all_playbooks(self):
        orch = RegimeV2Orchestrator.create("BTCUSDT", "1h")
        snapshot = orch.analyze(_make_shock_ohlcv())

        assert snapshot.evidence.summary_label == "shock"
        assert snapshot.evidence.shock_risk >= 0.85
        assert snapshot.policy.max_position_scale == 0.0
        assert snapshot.policy.trend_score == 0.0
        assert snapshot.policy.breakout_score == 0.0
        assert snapshot.policy.no_trade_reason is not None

    def test_invalid_ohlc_shape_degrades_confidence(self):
        df = _make_ohlcv()
        df.iloc[-1, df.columns.get_loc("high")] = df.iloc[-1]["low"] * 0.90
        orch = RegimeV2Orchestrator.create("BTCUSDT", "1h")
        snapshot = orch.analyze(df)

        assert snapshot.data_quality.usable is False
        assert "invalid_ohlc_shape" in snapshot.data_quality.reasons
        assert snapshot.evidence.uncertainty == 1.0
        assert snapshot.policy.max_position_scale == 0.0


class TestRegimeV2BinanceNativeScript:
    def test_normalize_binance_native_ohlcv(self):
        raw = pd.DataFrame(
            {
                "timestamp": [1_700_000_000_000, 1_700_003_600_000],
                "open": ["100", "101"],
                "high": ["102", "103"],
                "low": ["99", "100"],
                "close": ["101", "102"],
                "volume": ["1000", "1100"],
                "taker_buy_base": ["500", "550"],
            }
        )

        normalized = normalize_binance_native_ohlcv(raw, timeframe="1h")

        assert list(normalized.columns) == [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "bar_available_at",
        ]
        assert str(normalized.index.tz) == "UTC"
        assert normalized.iloc[0]["close"] == 101.0

    def test_trend_family_cli_args_parse(self):
        args = parse_trend_family_args(
            [
                "--candidate-csv",
                "/tmp/candidates.csv",
                "--symbol",
                "BTCUSDT",
                "--timeframe",
                "4h",
                "--model-name",
                "MomentumV2",
                "--model-name",
                "PriceActionV2",
            ]
        )

        assert args.candidate_csv == "/tmp/candidates.csv"
        assert args.symbol == "BTCUSDT"
        assert args.timeframe == "4h"
        assert args.model_name == ["MomentumV2", "PriceActionV2"]

    def test_ablation_cli_args_parse(self):
        args = parse_ablation_args(
            [
                "--symbol",
                "BTCUSDT",
                "--timeframe",
                "4h",
                "--limit",
                "500",
                "--horizon-bars",
                "6",
                "--fee-bps",
                "4",
            ]
        )

        assert args.symbol == "BTCUSDT"
        assert args.timeframe == "4h"
        assert args.limit == 500
        assert args.horizon_bars == 6
        assert args.fee_bps == 4.0

    @pytest.mark.asyncio
    async def test_fetch_binance_native_ohlcv_uses_adapter(self, monkeypatch):
        raw = pd.DataFrame(
            {
                "timestamp": [1_700_000_000_000],
                "open": ["100"],
                "high": ["102"],
                "low": ["99"],
                "close": ["101"],
                "volume": ["1000"],
            }
        )

        class FakeAdapter:
            async def get_historical_ohlcv(
                self,
                symbol,
                timeframe,
                since=None,
                until=None,
                limit=None,
                **kwargs,
            ):
                assert symbol == "BTCUSDT"
                assert timeframe == "1h"
                assert limit == 1
                assert kwargs["include_close_time"] is True
                return raw

        import libs.models.regime_v2.scripts.compare_binance_native as script

        monkeypatch.setattr(script, "BinanceNativeAdapter", lambda: FakeAdapter())
        normalized = await fetch_binance_native_ohlcv(symbol="btcusdt", timeframe="1h", limit=1)

        assert normalized.iloc[0]["open"] == 100.0
        assert normalized.iloc[0]["close"] == 101.0

    def test_normalize_binance_native_ohlcv_uses_exchange_close_time(self):
        raw = pd.DataFrame(
            {
                "timestamp": [1_700_000_000_000],
                "open": ["100"],
                "high": ["102"],
                "low": ["99"],
                "close": ["101"],
                "volume": ["1000"],
                "close_time": [1_700_000_003_599],
            }
        )

        normalized = normalize_binance_native_ohlcv(raw, timeframe="1h")

        assert normalized.attrs["bar_availability_source"] == "exchange_close_time"
        assert normalized.iloc[0]["bar_available_at"] == pd.Timestamp(
            "2023-11-14T22:13:23.599Z"
        )

    def test_normalize_binance_native_ohlcv_derives_strict_fixed_interval(self):
        raw = pd.DataFrame(
            {
                "timestamp": [1_700_000_000_000],
                "open": ["100"],
                "high": ["102"],
                "low": ["99"],
                "close": ["101"],
                "volume": ["1000"],
            }
        )

        normalized = normalize_binance_native_ohlcv(raw, timeframe="1h")

        assert normalized.attrs["bar_availability_source"] == "fixed_interval_derived"
        assert normalized.iloc[0]["bar_available_at"] == normalized.index[0] + pd.Timedelta(hours=1)


class TestRegimeV2ComparisonHarness:
    def test_comparison_runs_regime_v2_and_no_regime(self):
        result = run_regime_comparison(
            _make_ohlcv(),
            asset="BTCUSDT",
            timeframe="1h",
            config=RegimeComparisonConfig(
                horizon_bars=6,
                include_legacy_regime=False,
                include_regime_classification=False,
            ),
        )

        assert "regime_v2_summary_label" in result.frame.columns
        assert "regime_v2_policy_trend_score" in result.frame.columns
        assert "no_regime_label" in result.frame.columns
        assert result.summary["modules_present"]["regime_v2"] is True
        assert result.summary["modules_present"]["no_regime"] is True
        assert result.summary["regime_v2"]["label_distribution"]
        assert "evidence_quantiles" in result.summary["regime_v2"]
        assert "pre_breakout_setup_score" in result.summary["regime_v2"]["evidence_quantiles"]
        assert "policy_score_quantiles" in result.summary["regime_v2"]
        assert result.errors == {}

    def test_comparison_records_optional_module_errors(self, monkeypatch):
        from libs.models.regime_v2.evaluation import comparison

        def boom(*args, **kwargs):
            raise RuntimeError("legacy unavailable")

        monkeypatch.setattr(comparison, "_legacy_regime_frame", boom)
        result = comparison.run_regime_comparison(
            _make_ohlcv(),
            asset="BTCUSDT",
            timeframe="1h",
            config=comparison.RegimeComparisonConfig(
                include_legacy_regime=True,
                include_regime_classification=False,
            ),
        )

        assert result.summary["modules_present"]["regime_v2"] is True
        assert "legacy_regime" in result.errors
        assert "legacy unavailable" in result.errors["legacy_regime"]


class TestRegimeV2OverlayWindowValidation:
    def test_overlay_validation_cli_args_parse(self):
        args = parse_overlay_validation_args(
            [
                "--symbol",
                "BTCUSDT",
                "--timeframe",
                "4h",
                "--fee-bps",
                "2",
                "--fee-bps",
                "5",
                "--window-bars",
                "250",
            ]
        )

        assert args.symbol == "BTCUSDT"
        assert args.timeframe == "4h"
        assert args.fee_bps == [0.0, 2.0, 5.0]
        assert args.window_bars == 250

    def test_overlay_window_validation_returns_summary_and_metrics(self):
        result = run_overlay_window_validation(
            _make_ohlcv(),
            asset="BTCUSDT",
            timeframe="1h",
            config=OverlayWindowValidationConfig(
                horizon_bars=4,
                window_bars=80,
                step_bars=40,
                min_count=1,
                fee_bps_values=(0.0, 2.0),
                candidate_models=("Momentum", "TrendFollowing"),
            ),
        )

        assert "summary" in result
        assert "metrics" in result
        assert result["summary"]["window_count"] == len(result["metrics"])
        assert result["summary"]["horizon_bars"] == 4
        assert set(result["summary"]["fee_bps_values"]) == {0.0, 2.0}
        assert "fee_summary" in result["summary"]
        assert set(result["summary"]["fee_summary"].keys()) == {"0.0", "2.0"}


class TestRegimeV2SelectionOverlay:
    def test_selection_overlay_improves_top_pick_when_regime_aligned_model_exists(self):
        idx = pd.date_range("2026-01-01", periods=4, freq="h", tz="UTC")
        comparison = pd.DataFrame(
            {
                "fwd_return": [0.03, -0.025, 0.02, -0.02],
                "regime_v2_policy_allow_trend_following": [True, True, True, True],
                "regime_v2_policy_trend_score": [0.8, 0.8, 0.8, 0.8],
                "regime_v2_trend_direction": ["bull", "bear", "bull", "bear"],
            },
            index=idx,
        )
        candidates = pd.DataFrame(
            {
                "timestamp": list(idx) * 2,
                "model_name": ["OtherModel"] * 4 + ["Momentum"] * 4,
                "direction": [-1, 1, -1, 1, 1, -1, 1, -1],
                "edge_score": [1.0, 1.0, 1.0, 1.0, 0.9, 0.9, 0.9, 0.9],
                "conviction": [1.0] * 8,
            }
        )

        result = run_regime_v2_trend_selection_overlay(
            comparison,
            candidates,
            config=RegimeV2TrendOverlayConfig(min_count=1, aligned_boost=0.5, conflict_penalty=0.7),
        )

        assert result.summary["overlay_better"] is True
        assert result.summary["lift_vs_baseline"] is not None and result.summary["lift_vs_baseline"] > 0.0
        assert result.overlay.win_rate == 1.0
        assert result.baseline.win_rate == 0.0
        assert result.summary["changed_pick_rate"] == 1.0

    def test_selection_overlay_can_suppress_conflicts(self):
        idx = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
        comparison = pd.DataFrame(
            {
                "fwd_return": [0.02, -0.02],
                "regime_v2_policy_allow_trend_following": [True, True],
                "regime_v2_policy_trend_score": [0.8, 0.8],
                "regime_v2_trend_direction": ["bull", "bear"],
            },
            index=idx,
        )
        candidates = pd.DataFrame(
            {
                "timestamp": idx,
                "model_name": ["Momentum", "Momentum"],
                "direction": [-1, 1],
                "edge_score": [1.0, 1.0],
                "conviction": [1.0, 1.0],
            }
        )

        result = run_regime_v2_trend_selection_overlay(
            comparison,
            candidates,
            config=RegimeV2TrendOverlayConfig(min_count=1, suppress_conflicts=True),
        )

        assert result.summary["conflict_penalty_pick_rate"] == 1.0
        assert result.overlay.mean_edge == result.baseline.mean_edge

    def test_selection_overlay_supports_phase4b_mean_reversion_playbook(self):
        idx = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
        comparison = pd.DataFrame(
            {
                "fwd_return": [0.02, -0.02],
                "regime_v2_policy_allow_mean_reversion": [True, True],
                "regime_v2_policy_mean_reversion_score": [0.8, 0.8],
                "regime_v2_trend_direction": ["neutral", "neutral"],
            },
            index=idx,
        )
        candidates = pd.DataFrame(
            {
                "timestamp": list(idx) * 2,
                "model_name": ["OtherModel", "OtherModel", "RegimePullbackScorer", "RegimePullbackScorer"],
                "direction": [-1, 1, 1, -1],
                "edge_score": [1.0, 1.0, 0.9, 0.9],
                "conviction": [1.0] * 4,
            }
        )

        result = run_regime_v2_trend_selection_overlay(
            comparison,
            candidates,
            config=RegimeV2TrendOverlayConfig(min_count=1, aligned_boost=0.5),
        )

        assert result.summary["overlay_better"] is True
        assert result.summary["changed_pick_rate"] == 1.0
        assert result.overlay.win_rate == 1.0
        assert result.gated.count == 2
        assert set(result.selected_frame["_overlay_playbook"].dropna()) == {"mean_reversion"}

    def test_selection_overlay_supports_phase4b_breakout_playbook(self):
        idx = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
        comparison = pd.DataFrame(
            {
                "fwd_return": [0.02, -0.02],
                "regime_v2_policy_allow_breakout": [True, True],
                "regime_v2_policy_breakout_score": [0.8, 0.8],
                "regime_v2_trend_direction": ["bull", "bear"],
            },
            index=idx,
        )
        candidates = pd.DataFrame(
            {
                "timestamp": list(idx) * 2,
                "model_name": ["OtherModel", "OtherModel", "SqueezeBreakout", "SqueezeBreakout"],
                "direction": [-1, 1, 1, -1],
                "edge_score": [1.0, 1.0, 0.9, 0.9],
                "conviction": [1.0] * 4,
            }
        )

        result = run_regime_v2_trend_selection_overlay(
            comparison,
            candidates,
            config=RegimeV2TrendOverlayConfig(min_count=1, aligned_boost=0.5),
        )

        assert result.summary["overlay_better"] is True
        assert result.summary["changed_pick_rate"] == 1.0
        assert result.overlay.win_rate == 1.0
        assert result.gated.count == 2
        assert set(result.selected_frame["_overlay_playbook"].dropna()) == {"breakout"}


class TestRegimeV2CandidateExport:
    def test_standard_feature_frame_adds_required_indicators(self):
        features = build_standard_feature_frame(_make_ohlcv())

        for column in [
            "EMA_fast",
            "EMA_slow",
            "MACD_line",
            "MACD_signal",
            "MACD_histogram",
            "RSI",
            "ATR",
            "KAMA_fast",
            "KAMA_slow",
            "BollingerBands_upper",
            "BollingerBands_lower",
            "KeltnerChannel_upper",
            "KeltnerChannel_lower",
            "CCI",
            "ADX",
            "ADX_adx",
            "ADX_plus_di",
            "ADX_minus_di",
            "ADLine",
            "MFI",
            "Momentum",
            "eng_mean_reversion_z",
            "eng_squeeze_intensity",
            "eng_regime_score",
        ]:
            assert column in features.columns
        assert features["ATR"].notna().sum() > 0

    def test_standard_feature_frame_preserves_precomputed_columns(self):
        source = _make_ohlcv(120)
        source["RSI"] = 31.0
        source["eng_regime_score"] = -0.4
        source["eng_mean_reversion_z"] = -1.8

        features = build_standard_feature_frame(source)

        assert features["RSI"].dropna().eq(31.0).all()
        assert features["eng_regime_score"].dropna().eq(-0.4).all()
        assert features["eng_mean_reversion_z"].dropna().eq(-1.8).all()

    def test_export_builtin_trend_candidates_from_ohlcv(self):
        candidates = export_builtin_trend_candidates(
            _make_ohlcv(),
            asset="BTCUSDT",
            timeframe="1h",
            config=TrendCandidateExportConfig(models=("Momentum", "TrendFollowing")),
        )

        assert not candidates.empty
        assert {"timestamp", "model_name", "direction", "edge_score", "conviction"}.issubset(candidates.columns)
        assert set(candidates["model_name"]).issubset({"Momentum", "TrendFollowing"})
        assert set(candidates["direction"].unique()).issubset({-1, 1})

    def test_trendline_dataframe_export(self):
        from libs.models.regime_v2.evaluation import export_trendline_candidates

        idx = pd.date_range("2026-01-01", periods=4, freq="h", tz="UTC")
        source = pd.DataFrame(
            {
                "trendline_direction": [1, -1, 0, 1],
                "trendline_score": [0.8, 0.7, 0.9, 0.1],
                "trendline_confidence": [0.6, 0.9, 0.9, 0.5],
            },
            index=idx,
        )
        candidates = export_trendline_candidates(source, asset="BTCUSDT", timeframe="1h")

        assert list(candidates["direction"]) == [1, -1, 1]
        assert list(candidates["model_name"].unique()) == ["Trendline"]
        assert candidates["edge_score"].tolist() == [0.8, 0.7, 0.1]
        assert candidates["conviction"].tolist() == [0.6, 0.9, 0.5]

    def test_builtin_export_can_include_trendline_family(self):
        ohlcv = _make_ohlcv(80)
        ohlcv["trendline_direction"] = 1
        ohlcv["trendline_score"] = 0.8
        candidates = export_builtin_trend_candidates(
            ohlcv,
            asset="BTCUSDT",
            timeframe="1h",
            config=TrendCandidateExportConfig(models=("Trendline",), min_abs_edge=0.2),
        )

        assert not candidates.empty
        assert set(candidates["model_name"]) == {"Trendline"}
        assert set(candidates["direction"]) == {1}

    def test_builtin_export_can_include_phase4b_pullback_and_squeeze_families(self):
        features = _make_ohlcv(120)
        features["RSI"] = 30.0
        features["eng_regime_score"] = -0.5
        features["eng_mean_reversion_z"] = -2.0
        features["eng_squeeze_intensity"] = 0.1
        features["eng_btc_dominance_regime"] = 0.0
        features["eng_market_cap_breadth"] = 0.0
        features["eng_cross_asset_regime_state"] = 0
        features["eng_regime_alignment_score"] = 0.0

        candidates = export_builtin_trend_candidates(
            features,
            asset="BTCUSDT",
            timeframe="1h",
            config=TrendCandidateExportConfig(models=("RegimePullbackScorer", "SqueezeBreakout"), include_flat=True),
        )

        assert not candidates.empty
        assert {"RegimePullbackScorer", "SqueezeBreakout"}.issubset(set(candidates["model_name"]))
        assert set(candidates["source_type"]).issubset({"threshold", "scoring"})
        assert set(candidates["direction"].unique()).issubset({-1, 0, 1})

    def test_builtin_trend_cli_args_parse(self):
        args = parse_builtin_trend_args(
            [
                "--symbol",
                "BTCUSDT",
                "--timeframe",
                "4h",
                "--model",
                "Momentum",
                "--model",
                "TrendFollowing",
            ]
        )

        assert args.symbol == "BTCUSDT"
        assert args.timeframe == "4h"
        assert args.model == ["Momentum", "TrendFollowing"]

        overlay_args = parse_builtin_trend_args(
            ["--symbol", "BTCUSDT", "--timeframe", "4h", "--top-k", "2", "--aligned-boost", "0.4", "--suppress-conflicts"]
        )
        assert overlay_args.top_k == 2
        assert overlay_args.aligned_boost == 0.4
        assert overlay_args.suppress_conflicts is True


class TestRegimeV2TrendFamilyAblation:
    def test_trend_family_ablation_rewards_regime_aligned_candidates(self):
        idx = pd.date_range("2026-01-01", periods=8, freq="h", tz="UTC")
        comparison = pd.DataFrame(
            {
                "fwd_return": [0.03, -0.025, 0.005, -0.004, 0.02, -0.02, 0.001, -0.001],
                "regime_v2_policy_allow_trend_following": [True, True, False, False, True, True, False, False],
                "regime_v2_policy_trend_score": [0.8, 0.7, 0.1, 0.1, 0.9, 0.85, 0.0, 0.0],
                "regime_v2_trend_direction": ["bull", "bear", "bull", "bear", "bull", "bear", "neutral", "neutral"],
            },
            index=idx,
        )
        candidates = pd.DataFrame(
            {
                "timestamp": idx,
                "model_name": ["MomentumV2"] * len(idx),
                "direction": [1, -1, -1, 1, 1, -1, 1, -1],
                "edge_score": [1.0] * len(idx),
                "conviction": [1.0] * len(idx),
            }
        )

        result = run_trend_family_ablation(
            comparison,
            candidates,
            config=TrendFamilyAblationConfig(min_count=1, trend_score_floor=0.24, top_quantile=0.50),
        )
        metric = next(
            m for m in result.metrics
            if m.model_name == "MomentumV2" and m.filter_name == "regime_trend_allowed_agree"
        )

        assert metric.count == 4
        assert metric.mean_edge is not None and metric.mean_edge > 0.0
        assert metric.lift_vs_baseline is not None and metric.lift_vs_baseline > 0.0
        assert metric.win_rate == 1.0
        assert result.summary["best_filter"] is not None

    def test_trend_family_ablation_accepts_all_aggregate(self):
        idx = pd.date_range("2026-01-01", periods=4, freq="h", tz="UTC")
        comparison = pd.DataFrame(
            {
                "fwd_return": [0.02, -0.02, 0.01, -0.01],
                "regime_v2_policy_allow_trend_following": [True, True, False, False],
                "regime_v2_policy_trend_score": [0.9, 0.9, 0.0, 0.0],
                "regime_v2_trend_direction": ["bull", "bear", "neutral", "neutral"],
            },
            index=idx,
        )
        candidates = pd.DataFrame(
            {
                "timestamp": idx,
                "model_name": ["MomentumV2", "PriceActionV2", "MomentumV2", "PriceActionV2"],
                "direction": [1, -1, 1, -1],
            }
        )

        result = run_trend_family_ablation(
            comparison,
            candidates,
            config=TrendFamilyAblationConfig(min_count=1),
        )

        assert any(metric.model_name == "__all__" for metric in result.metrics)
        assert result.joined_frame["model_name"].nunique() == 2


class TestRegimeV2DownstreamAblation:
    def test_downstream_ablation_runs_on_comparison_frame(self):
        comparison = run_regime_comparison(
            _make_ohlcv(),
            asset="BTCUSDT",
            timeframe="1h",
            config=RegimeComparisonConfig(
                horizon_bars=6,
                include_legacy_regime=False,
                include_regime_classification=False,
            ),
        )

        result = run_downstream_ablation(
            comparison.frame,
            config=DownstreamAblationConfig(min_count=1, top_quantile=0.75, score_floor=0.0),
        )

        names = {metric.name for metric in result.metrics}
        assert "baseline_all_abs_move" in names
        assert "regime_v2_trend_allowed_directional" in names
        assert result.summary["metric_count"] == len(result.metrics)
        assert "best_by_lift" in result.summary

    def test_downstream_ablation_directional_trend_lift(self):
        frame = pd.DataFrame(
            {
                "fwd_return": [0.03, -0.025, -0.02, 0.01, 0.002, -0.001],
                "fwd_abs_return": [0.03, 0.025, 0.02, 0.01, 0.002, 0.001],
                "regime_v2_policy_allow_trend_following": [True, True, False, False, False, False],
                "regime_v2_policy_trend_score": [0.9, 0.8, 0.0, 0.0, 0.0, 0.0],
                "regime_v2_trend_direction": ["bull", "bear", "bull", "bear", "neutral", "neutral"],
            }
        )

        result = run_downstream_ablation(
            frame,
            config=DownstreamAblationConfig(min_count=1, top_quantile=0.50, score_floor=0.0),
        )
        trend_metric = next(metric for metric in result.metrics if metric.name == "regime_v2_trend_allowed_directional")

        assert trend_metric.count == 2
        assert trend_metric.mean_edge is not None and trend_metric.mean_edge > 0.0
        assert trend_metric.win_rate == 1.0
        assert trend_metric.lift_vs_baseline is not None and trend_metric.lift_vs_baseline > 0.0


class TestRegimeV2FeatureProducerAdapter:
    def test_adapter_serializes_nested_and_top_level_fields(self):
        producer = RegimeV2FeatureProducer("BTCUSDT", "1h")
        payload = producer.analyze(
            _make_ohlcv().to_dict("records"),
            latest_features={"eng_regime_alignment_score": 0.5, "RSI": 50.0},
        )

        assert "evidence" in payload
        assert "policy" in payload
        assert "data_quality" in payload
        assert payload["summary_label"] == payload["evidence"]["summary_label"]
        assert payload["confidence"] == payload["evidence"]["confidence"]
        assert "trend_score" in payload["policy"]


class TestRegimeV2Policy:
    def test_policy_allows_trend_when_evidence_is_clean(self):
        evidence = RegimeEvidence(
            timestamp=1,
            asset="BTCUSDT",
            timeframe="1h",
            trend_direction="bull",
            trend_strength=0.8,
            trend_persistence=0.75,
            trend_confidence=0.8,
            volatility_percentile=50.0,
            volatility_state="normal",
            compression_score=0.2,
            shock_risk=0.1,
            mean_reversion_score=0.2,
            range_quality=0.3,
            chop_risk=0.2,
            structural_break_risk=0.2,
            breakout_quality=0.4,
            false_breakout_risk=0.2,
            market_context_score=0.2,
            breadth_confirmation=0.2,
            liquidity_stress=0.0,
            confidence=0.75,
            uncertainty=0.25,
            summary_label="bull_trend",
        )
        policy = evidence_to_policy(evidence, PolicyConfig())
        assert policy.allow_trend_following is True
        assert policy.max_position_scale > 0.0
        assert policy.no_trade_reason is None

    def test_policy_blocks_when_uncertainty_is_extreme(self):
        evidence = RegimeEvidence(
            timestamp=1,
            asset="BTCUSDT",
            timeframe="1h",
            trend_direction="bull",
            trend_strength=0.9,
            trend_persistence=0.8,
            trend_confidence=0.9,
            volatility_percentile=90.0,
            volatility_state="shock",
            compression_score=0.0,
            shock_risk=0.9,
            mean_reversion_score=0.0,
            range_quality=0.0,
            chop_risk=0.7,
            structural_break_risk=0.9,
            breakout_quality=0.2,
            false_breakout_risk=0.8,
            market_context_score=-0.5,
            breadth_confirmation=-0.5,
            liquidity_stress=0.1,
            confidence=0.5,
            uncertainty=0.9,
            summary_label="shock",
        )
        policy = evidence_to_policy(evidence, PolicyConfig())
        assert policy.max_position_scale == 0.0
        assert policy.no_trade_reason is not None
        assert "uncertainty_too_high" in policy.reasons

    def test_policy_config_overrides_drive_risk_multipliers(self):
        evidence = RegimeEvidence(
            timestamp=1,
            asset="BTCUSDT",
            timeframe="1h",
            trend_direction="bull",
            trend_strength=0.8,
            trend_persistence=0.75,
            trend_confidence=0.8,
            volatility_percentile=50.0,
            volatility_state="normal",
            compression_score=0.2,
            shock_risk=0.1,
            mean_reversion_score=0.2,
            range_quality=0.3,
            chop_risk=0.2,
            structural_break_risk=0.2,
            breakout_quality=0.4,
            false_breakout_risk=0.2,
            market_context_score=0.2,
            breadth_confirmation=0.2,
            liquidity_stress=0.0,
            confidence=0.75,
            uncertainty=0.25,
            summary_label="bull_trend",
        )

        policy = evidence_to_policy(
            evidence,
            PolicyConfig(
                stop_base=1.8,
                stop_shock_weight=0.0,
                stop_break_weight=0.0,
                stop_min=0.0,
                stop_max=3.0,
                target_base=1.6,
                target_trend_weight=0.0,
                target_breakout_weight=0.0,
                target_min=0.0,
                target_max=3.0,
            ),
        )

        assert policy.stop_multiplier == 1.8
        assert policy.target_multiplier == 1.6
