"""
Regime Hyperparameter Optimizer.

Uses Optuna (Bayesian TPE) to optimize 5 params per asset per timeframe:
  bcpd_hazard_lambda, bcpd_signal_threshold,
  vol_high_percentile, vol_lookback, hmm_retrain_window

Objective: weighted composite of 5 benchmark tiers with Tier 3 validity gate.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, List, Optional

import numpy as np
import pandas as pd

from libs.regime.optimization.benchmarks import (
    changepoint_quality,
    predictive_power,
    stability,
    statistical_validity,
    strategy_utility,
    truthfulness,
)
from libs.regime.optimization.models import (
    BenchmarkResults,
    OptimizationConfig,
    OptimizationResult,
    OptimizationWeights,
    TrialResult,
)
from libs.regime.optimization.walk_forward import WalkForwardValidator

try:
    import optuna
    from optuna.samplers import CmaEsSampler, RandomSampler, TPESampler
    from optuna.pruners import HyperbandPruner, MedianPruner

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False

logger = logging.getLogger("app.regime")


def _default_orchestrator_factory(params: dict, asset: str, timeframe: str):
    """Create RegimeOrchestrator with the given trial params."""
    from libs.regime.orchestrator import RegimeOrchestrator
    _INT_KEYS = {
        "vol_lookback", "hmm_retrain_window", "hurst_lookback", "min_dwell_bars",
        "agg_direction_period", "hilbert_min_period", "hilbert_max_period",
        "roc_std_window",
    }
    clean = {k: int(v) if k in _INT_KEYS else v for k, v in params.items()}
    return RegimeOrchestrator.create(asset=asset, timeframe=timeframe, **clean)


class RegimeOptimizer:
    """
    Bayesian optimizer for the 4-layer regime detection pipeline.

    Usage
    -----
    config = OptimizationConfig(n_trials=100, timeout_seconds=3600)
    optimizer = RegimeOptimizer(config)
    result = optimizer.optimize(df, asset="BTCUSDT", timeframe="1h")
    result.apply_to_config("src/libs/regime/config/regime.yaml")
    """

    def __init__(
        self,
        config: Optional[OptimizationConfig] = None,
        orchestrator_factory: Optional[Callable] = None,
    ):
        if not OPTUNA_AVAILABLE:
            raise ImportError("Optuna required: pip install optuna")
        self.config = config or OptimizationConfig()
        # Apply objective_mode to weights
        if self.config.objective_mode == "classification":
            self.config.weights = OptimizationWeights.classification_only()
        elif self.config.objective_mode == "balanced":
            self.config.weights = OptimizationWeights.balanced()
        self.orchestrator_factory = orchestrator_factory or _default_orchestrator_factory
        self._walk_forward = WalkForwardValidator(
            train_bars=self.config.walk_forward.train_bars,
            test_bars=self.config.walk_forward.test_bars,
            step_bars=self.config.walk_forward.step_bars,
            purge_bars=self.config.walk_forward.purge_bars,
            min_train_bars=self.config.walk_forward.min_train_bars,
        )
        self._all_trials: List[TrialResult] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(
        self,
        df: pd.DataFrame,
        asset: str = "UNKNOWN",
        timeframe: str = "1h",
        n_trials: Optional[int] = None,
        timeout: Optional[int] = None,
        callbacks: Optional[List[Callable]] = None,
    ) -> OptimizationResult:
        """
        Run full Bayesian optimization and return best result.

        Parameters
        ----------
        df        : OHLCV DataFrame with 'close' column
        asset     : asset symbol (e.g. "BTCUSDT")
        timeframe : timeframe string (e.g. "1h")
        n_trials  : override config n_trials
        timeout   : override config timeout_seconds
        callbacks : optional list of Optuna callbacks (called after each trial)
        """
        n_trials = n_trials or self.config.n_trials
        timeout_sec = timeout or self.config.timeout_seconds
        self._all_trials = []

        # Adjust purge gap for the actual timeframe
        self._walk_forward.purge_bars = (
            self.config.walk_forward.purge_bars_for_timeframe(timeframe)
        )

        n_folds = self._walk_forward.n_folds(len(df))
        logger.info(
            "Starting optimization: %s %s | %d trials | %d folds | %d bars",
            asset, timeframe, n_trials, n_folds, len(df),
        )

        start_time = time.time()
        study = optuna.create_study(
            direction="maximize",
            sampler=self._create_sampler(),
            pruner=self._create_pruner(),
        )
        study.optimize(
            lambda trial: self._objective(trial, df, asset, timeframe),
            n_trials=n_trials,
            timeout=timeout_sec,
            n_jobs=self.config.n_jobs,
            show_progress_bar=False,
            callbacks=callbacks or [],
        )
        total_time = time.time() - start_time

        best_trial = study.best_trial
        best_params = best_trial.params
        best_benchmarks = self._compute_all_benchmarks(df, best_params, asset, timeframe)
        n_passed = sum(1 for t in self._all_trials if t.passed_gate)

        logger.info(
            "Optimization complete: best=%.4f | passed_gate=%d/%d | time=%.1fs",
            best_trial.value, n_passed, len(self._all_trials), total_time,
        )

        return OptimizationResult(
            asset=asset,
            timeframe=timeframe,
            best_params=best_params,
            best_objective=float(best_trial.value),
            best_benchmarks=best_benchmarks,
            n_trials_passed_gate=n_passed,
            n_trials_total=len(self._all_trials),
            total_time_seconds=total_time,
            config=self.config,
            all_trials=self._all_trials,
        )

    # ------------------------------------------------------------------
    # Optuna objective
    # ------------------------------------------------------------------

    def _objective(
        self,
        trial: "optuna.Trial",
        df: pd.DataFrame,
        asset: str,
        timeframe: str,
    ) -> float:
        params = self._sample_params(trial)

        fold_scores: List[float] = []
        fold_benchmarks: List[BenchmarkResults] = []

        for _, train_df, test_df in self._walk_forward.iterate_splits(df):
            score, bench = self._evaluate_fold(train_df, test_df, params, asset, timeframe)
            fold_scores.append(score)
            fold_benchmarks.append(bench)

        mean_score = float(np.mean(fold_scores)) if fold_scores else 0.0
        agg_bench = self._aggregate_benchmarks(fold_benchmarks)
        passed_gate = agg_bench.passed_validity_gate

        trial_result = TrialResult(
            trial_id=trial.number,
            params=params,
            objective_value=mean_score,
            benchmark_results=agg_bench,
            passed_gate=passed_gate,
            fold_results=fold_benchmarks,
        )
        self._all_trials.append(trial_result)
        return mean_score

    def _sample_params(self, trial: "optuna.Trial") -> dict:
        cfg = self.config
        return {
            "bcpd_hazard_lambda": trial.suggest_float("bcpd_hazard_lambda", *cfg.hazard_lambda),
            "bcpd_signal_threshold": trial.suggest_float("bcpd_signal_threshold", *cfg.signal_threshold),
            "vol_high_percentile": trial.suggest_float("vol_high_percentile", *cfg.vol_high_percentile),
            "vol_lookback": trial.suggest_int("vol_lookback", *cfg.vol_lookback),
            "hmm_retrain_window": trial.suggest_int("hmm_retrain_window", *cfg.hmm_retrain_window),
            "hurst_lookback": trial.suggest_int("hurst_lookback", *cfg.hurst_lookback),
            "min_dwell_bars": trial.suggest_int("min_dwell_bars", *cfg.min_dwell_bars),
            "agg_direction_period": trial.suggest_int("agg_direction_period", *cfg.agg_direction_period),
            "agg_bull_roc_thresh": trial.suggest_float("agg_bull_roc_thresh", *cfg.agg_bull_roc_thresh),
            "agg_vol_squeeze_pct": trial.suggest_float("agg_vol_squeeze_pct", *cfg.agg_vol_squeeze_pct),
            "hilbert_min_period": trial.suggest_int("hilbert_min_period", *cfg.hilbert_min_period),
            "hilbert_max_period": trial.suggest_int("hilbert_max_period", *cfg.hilbert_max_period),
            # Phase 3-4 new params
            "bcpd_hazard_shape": trial.suggest_float("bcpd_hazard_shape", *cfg.bcpd_hazard_shape),
            "hmm_student_df": trial.suggest_float("hmm_student_df", *cfg.hmm_student_df),
            "vol_hysteresis_band": trial.suggest_float("vol_hysteresis_band", *cfg.vol_hysteresis_band),
            "agg_cp_position_decay": trial.suggest_float("agg_cp_position_decay", *cfg.cp_position_decay),
            "hmm_crisis_vol_mult": trial.suggest_float("hmm_crisis_vol_mult", *cfg.hmm_crisis_vol_mult),
            "roc_std_window": trial.suggest_int("roc_std_window", *cfg.roc_std_window),
        }

    def _evaluate_fold(
        self,
        train_df: pd.DataFrame,
        test_df: pd.DataFrame,
        params: dict,
        asset: str,
        timeframe: str,
    ) -> tuple:
        """
        Fit on train_df (so HMM warms up), evaluate benchmarks on test_df.
        Returns (score, BenchmarkResults).
        """
        try:
            orch = self.orchestrator_factory(params, asset, timeframe)
            # Warm up on train data so HMM fits
            orch.analyze_series(train_df)
            # Reset only HMM model age; keep state for test continuity
            # (simulate live bar-by-bar continuation)
            features_df = orch.analyze_series(test_df)
            hmm_diag = orch.hmm_classifier.diagnostics()
        except Exception as exc:
            logger.debug("Fold eval failed: %s", exc)
            return 0.0, BenchmarkResults()

        if features_df is None or len(features_df) < 20:
            return 0.0, BenchmarkResults()

        returns = np.log(
            test_df["close"].values / (test_df["close"].shift(1).values + 1e-10)
        )
        returns = returns[1:]  # drop first NaN

        return self._compute_fold_score(features_df, returns, price_df=test_df, hmm_diag=hmm_diag)

    def _compute_fold_score(
        self,
        features_df: pd.DataFrame,
        returns: np.ndarray,
        *,
        price_df: Optional[pd.DataFrame] = None,
        hmm_diag: Optional[dict] = None,
    ) -> tuple:
        """Compute composite score for one fold."""
        w = self.config.weights

        # Tier 1
        t1 = strategy_utility.compute(features_df, returns)
        # Tier 2
        t2 = predictive_power.compute(features_df, returns)
        # Tier 3 (gate)
        t3 = statistical_validity.compute(features_df, returns)
        # Tier 4
        t4 = stability.compute(features_df)
        # Tier 5
        t5 = changepoint_quality.compute(features_df, returns)
        # Supplemental truthfulness metrics (reporting-only)
        t6 = truthfulness.compute(features_df, returns, price_df=price_df)
        diag = hmm_diag or {}

        passed_gate = t3["passed_validity_gate"]
        gate_mult = statistical_validity.gate_penalty(
            t3["levene_p_value"],
            self.config.validity_p_threshold,
            self.config.validity_penalty,
            self.config.soft_gate,
        )
        cd_bonus = statistical_validity.cohens_d_bonus(t3["cohens_d"])

        # Tier 4: hard constraint (not weighted — prevents gaming via
        # inflating any param that suppresses regime transitions)
        stability_mult = 1.0
        if t4["avg_regime_duration"] < self.config.min_avg_regime_duration:
            stability_mult = self.config.stability_penalty
        elif t4["flip_flop_rate"] > self.config.max_flip_flop_rate:
            stability_mult = self.config.stability_penalty

        # Normalise metrics to [0, 1] range before weighting
        score = (
            w.sharpe_improvement * self._norm(t1["sharpe_improvement"], -2.0, 2.0)
            + w.drawdown_reduction * self._norm(t1["drawdown_reduction"], -0.5, 0.5)
            + w.forward_return_ic * self._norm(t2["forward_return_ic"], -0.5, 0.5)
            + w.vol_forecast_error * (1.0 - self._norm(t2["vol_forecast_error"], 0.0, 2.0))
            + w.ic_decay_score * self._norm(t2["ic_decay_score"], -0.5, 0.5)
            + w.cp_precision * t5["cp_precision"]
            + w.detection_lag * self._norm(1.0 / (t5["detection_lag"] + 1.0), 0.0, 1.0)
        ) * gate_mult * stability_mult + cd_bonus

        bench = BenchmarkResults(
            sharpe_improvement=t1["sharpe_improvement"],
            drawdown_reduction=t1["drawdown_reduction"],
            forward_return_ic=t2["forward_return_ic"],
            vol_forecast_error=t2["vol_forecast_error"],
            ic_decay_score=t2["ic_decay_score"],
            levene_p_value=t3["levene_p_value"],
            cohens_d=t3["cohens_d"],
            passed_validity_gate=passed_gate,
            avg_regime_duration=t4["avg_regime_duration"],
            flip_flop_rate=t4["flip_flop_rate"],
            transition_entropy=t4["transition_entropy"],
            cp_precision=t5["cp_precision"],
            detection_lag=t5["detection_lag"],
            cp_recall=t5["cp_recall"],
            baseline_sharpe_lift=t6["baseline_sharpe_lift"],
            baseline_ic_lift=t6["baseline_ic_lift"],
            persistence_sharpe_lift=t6["persistence_sharpe_lift"],
            persistence_ic_lift=t6["persistence_ic_lift"],
            vol_baseline_sharpe_lift=t6["vol_baseline_sharpe_lift"],
            vol_baseline_ic_lift=t6["vol_baseline_ic_lift"],
            adx_baseline_sharpe_lift=t6["adx_baseline_sharpe_lift"],
            adx_baseline_ic_lift=t6["adx_baseline_ic_lift"],
            shuffled_sharpe_lift=t6["shuffled_sharpe_lift"],
            shuffled_ic_lift=t6["shuffled_ic_lift"],
            proxy_trend_brier_score=t6["proxy_trend_brier_score"],
            proxy_trend_ece=t6["proxy_trend_ece"],
            passed_baseline_gate=t6["passed_baseline_gate"],
            passed_strict_baseline_gate=t6["passed_strict_baseline_gate"],
            strict_baseline_failure_count=t6["strict_baseline_failure_count"],
            hmm_fit_failure_rate=float(diag.get("fit_failure_rate", 0.0)),
            hmm_unstable_fit_rate=float(diag.get("unstable_fit_rate", 0.0)),
            hmm_zero_transition_fit_rate=float(diag.get("zero_transition_fit_rate", 0.0)),
        )
        return float(score), bench

    def _compute_all_benchmarks(
        self,
        df: pd.DataFrame,
        params: dict,
        asset: str,
        timeframe: str,
    ) -> BenchmarkResults:
        """Compute full benchmarks on the entire dataset for the best params."""
        try:
            orch = self.orchestrator_factory(params, asset, timeframe)
            features_df = orch.analyze_series(df)
            returns = np.log(
                df["close"].values / (df["close"].shift(1).values + 1e-10)
            )
            returns = returns[1:]
            hmm_diag = orch.hmm_classifier.diagnostics()
            _, bench = self._compute_fold_score(
                features_df,
                returns,
                price_df=df,
                hmm_diag=hmm_diag,
            )
            bench.n_bars = len(df)
            return bench
        except Exception as exc:
            logger.warning("Final benchmark computation failed: %s", exc)
            return BenchmarkResults()

    # ------------------------------------------------------------------
    # Optuna helpers
    # ------------------------------------------------------------------

    def _create_sampler(self):
        s = self.config.sampler.lower()
        if s == "tpe":
            return TPESampler(seed=42)
        if s == "cmaes":
            return CmaEsSampler(seed=42)
        return RandomSampler(seed=42)

    def _create_pruner(self):
        p = self.config.pruner.lower()
        if p == "median":
            return MedianPruner(n_startup_trials=5, n_warmup_steps=2)
        if p == "hyperband":
            return HyperbandPruner()
        return optuna.pruners.NopPruner()

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _norm(value: float, min_val: float, max_val: float) -> float:
        """Clamp and normalise value to [0, 1]."""
        if np.isnan(value):
            return 0.0
        clamped = max(min_val, min(max_val, value))
        rng = max_val - min_val
        return float((clamped - min_val) / rng) if rng > 0 else 0.0

    @staticmethod
    def _aggregate_benchmarks(folds: List[BenchmarkResults]) -> BenchmarkResults:
        """Average metrics across folds."""
        if not folds:
            return BenchmarkResults()
        fields = BenchmarkResults.__dataclass_fields__.keys()
        agg = {}
        for f in fields:
            vals = [getattr(b, f) for b in folds]
            if isinstance(vals[0], bool):
                agg[f] = all(vals)
            elif isinstance(vals[0], (int, float)):
                finite = [v for v in vals if np.isfinite(v)]
                agg[f] = float(np.mean(finite)) if finite else 0.0
            else:
                agg[f] = vals[0]
        return BenchmarkResults(**agg)
