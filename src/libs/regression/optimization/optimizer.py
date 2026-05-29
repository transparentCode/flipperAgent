"""
V2 Regression Optimizer (MOTPE).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import optuna
import pandas as pd

from app.regression.config.schema import OrchestratorConfig, OptimizationTier
from app.regression.contracts.context import PipelineRequest
from app.regression.contracts.result import RegressionResult
from app.regression.optimization.benchmarks import (
    band_calibration,
    confidence_correlation,
    direction_accuracy,
    residual_quality,
    strategy_utility,
)
from app.regression.optimization.benchmarks._common import extract_result_arrays
from app.regression.optimization.constants import BARS_PER_YEAR, DEFAULT_BARS_PER_YEAR
from app.regression.optimization.adaptive_thresholds import derive_thresholds
from app.regression.optimization.meta_filter import HarmonicStabilitySelector, MetaFilterSelector
from app.regression.optimization.models import (
    RegressionBenchmarkResults,
    RegressionOptimizationConfig,
    RegressionOptimizationResult,
    RegressionTrialResult,
)
from app.regression.optimization.search_space import SearchSpaceBuilder
from app.regression.optimization.walk_forward import WalkForwardValidator, WalkForwardSplit3Way

logger = logging.getLogger("app.regression.optimization")

# Suppress Optuna's verbose trial logging (we log our own summaries)
optuna.logging.set_verbosity(optuna.logging.WARNING)


class _ConvergenceCallback:
    """Early-stop when the Pareto front hasn't improved for `patience` trials.

    Does NOT trigger when the front is empty — an empty front means
    no feasible region has been found yet, so the optimizer should
    keep exploring rather than stop early.
    """

    def __init__(self, patience: int = 50):
        self._patience = patience
        self._best_count = 0
        self._stale = 0

    def __call__(self, study: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
        n_pareto = len(study.best_trials)

        # Don't count toward staleness if front is empty —
        # the search hasn't found a feasible region yet.
        if n_pareto == 0:
            return

        if n_pareto > self._best_count:
            self._best_count = n_pareto
            self._stale = 0
        else:
            self._stale += 1
        if self._stale >= self._patience:
            logger.info(
                f"Early stopping: Pareto front unchanged for {self._patience} trials "
                f"(front size={n_pareto})"
            )
            study.stop()


class RegressionMOTPEOptimizer:
    """
    Executes a Multi-Objective TPE optimization using a strict 3-way Walk-Forward split.
    Uses 10th percentile aggregation for worst-case stabilization.
    """

    def __init__(
        self,
        config: RegressionOptimizationConfig,
        orch_config: OrchestratorConfig,
        pipeline_factory: Callable[[Dict[str, Any], str, str], Tuple[Any, Any]],
    ):
        if config.n_jobs > 1:
            raise ValueError(
                "n_jobs > 1 is not thread-safe (shared _all_trials list). "
                "Use n_jobs=1 for sequential trial execution."
            )

        self.config = config
        self.orch_config = orch_config
        self.pipeline_factory = pipeline_factory
        
        # 3-way split walk forward
        self.walk_forward = WalkForwardValidator(
            train_bars=config.train_bars,
            validate_bars=config.validate_bars,
            test_bars=config.test_bars,
            step_bars=config.step_bars,
            purge_bars=config.purge_bars,
            min_train_bars=config.min_train_bars,
            max_train_ratio=config.max_train_ratio,
            expanding_window=config.expanding_window,
        )
        self.search_space_builder = SearchSpaceBuilder()
        if config.motpe.meta_filter_strategy == "harmonic_stability":
            self.meta_filter = HarmonicStabilitySelector(
                objectives=tuple(config.motpe.objectives)
            )
        else:
            self.meta_filter = MetaFilterSelector(
                metric=config.motpe.meta_filter_metric, minimize=True
            )
        self._all_trials: List[RegressionTrialResult] = []
        self._trials_lock = threading.Lock()

    def optimize(self, df: pd.DataFrame, asset: str, timeframe: str) -> RegressionOptimizationResult:
        """Run the MOTPE optimization pipeline."""
        t0 = time.time()
        self._all_trials.clear()

        # Resolve annualization factor from timeframe
        bars_per_year = BARS_PER_YEAR.get(timeframe, DEFAULT_BARS_PER_YEAR)
        if timeframe not in BARS_PER_YEAR:
            logger.warning(
                f"Unknown timeframe '{timeframe}' for annualization, "
                f"falling back to {DEFAULT_BARS_PER_YEAR} (1h)"
            )

        # 1. 3-Way Walk Forward Generation
        folds = self.walk_forward.get_splits(len(df))
        logger.info(f"Generated {len(folds)} 3-way folds for {asset} {timeframe}")

        # 2. Build Search Space Specs
        tier_str = self.config.optimization_tier
        if tier_str == "full":
            specs = self.search_space_builder.build_merged(
                self.orch_config,
                [OptimizationTier.GLOBAL, OptimizationTier.PER_TF],
                self.config,
            )
        else:
            tier = OptimizationTier(tier_str)
            specs = self.search_space_builder.build(self.orch_config, tier, self.config)
        if not specs:
            raise ValueError(
                f"No tunable parameters found for tier '{tier_str}'. "
                f"Check orchestrator config optimization.{{global_tunable, per_tf_tunable}}."
            )

        logger.info(f"Search space: {len(specs)}D — {[s.name for s in specs]}")

        # 2b. Derive adaptive constraint thresholds from OHLCV data
        derived = derive_thresholds(df, timeframe)
        self._derived_thresholds = derived

        # Override config floors with data-derived values
        self._active_direction_floor = derived.min_direction_floor
        self._active_sharpe_floor = derived.min_sharpe_floor
        self._active_coverage_cap = derived.coverage_cap

        # 3. MOTPE Sampler (seeded for reproducibility)
        # In Optuna 4.x, TPESampler auto-selects MOTPE for multi-objective studies
        directions = ["maximize", "maximize", "maximize"]

        def _constraints_func(trial: optuna.trial.FrozenTrial) -> list[float]:
            """Negative = feasible, positive = violated."""
            constraints = trial.user_attrs.get("constraints", [0.0, 0.0])
            return constraints

        sampler = optuna.samplers.TPESampler(
            seed=self.config.seed,
            constraints_func=_constraints_func,
        )
        study = optuna.create_study(directions=directions, sampler=sampler)

        # 4. Execution Loop with early stopping
        study.optimize(
            lambda trial: self._objective(
                trial, df, folds, specs, asset, timeframe, bars_per_year
            ),
            n_trials=self.config.n_trials,
            timeout=self.config.timeout_seconds,
            n_jobs=self.config.n_jobs,
            callbacks=[_ConvergenceCallback(patience=50)],
        )

        total_time = time.time() - t0
        passed_trials = [t for t in self._all_trials if t.passed_gate and t.passed_constraint]

        logger.info(
            f"Optimization complete: {len(self._all_trials)} trials evaluated, "
            f"{len(passed_trials)} passed gate+constraint, "
            f"{len(study.best_trials)} on Pareto front, "
            f"{total_time:.1f}s total"
        )

        if not study.best_trials:
            logger.warning("No Pareto front found (likely zero trials passed constraints).")
            if not self._all_trials:
                raise RuntimeError(
                    "All trials were pruned — no results to select from. "
                    "Consider relaxing gate/constraint thresholds or increasing n_trials."
                )
            best_candidate = sorted(
                self._all_trials,
                key=lambda t: t.benchmark_results.confidence_sharpe,
                reverse=True,
            )[0]
            pareto_candidates = [best_candidate.to_dict()]
        else:
            # 5. Tie-Breaker (Orthogonal Meta-Filter)
            pareto_trial_ids = {t.number for t in study.best_trials}
            pareto_results = [t for t in self._all_trials if t.trial_id in pareto_trial_ids]
            
            best_candidate = self.meta_filter.select_best_candidate(pareto_front=pareto_results)
            pareto_candidates = [t.to_dict() for t in pareto_results]

        # 6. Final OOS Evaluation
        final_oos_benchmarks = self._evaluate_oos(
            best_candidate.params, df, folds, asset, timeframe, bars_per_year
        )

        return RegressionOptimizationResult(
            asset=asset,
            timeframe=timeframe,
            best_params=best_candidate.params,
            best_objective_values=best_candidate.objective_values,
            best_benchmarks=final_oos_benchmarks,
            pareto_candidates=pareto_candidates,
            n_trials_passed_gate=len(passed_trials),
            n_trials_total=len(self._all_trials),
            total_time_seconds=total_time,
            config=self.config,
            derived_thresholds={
                "min_direction_floor": self._active_direction_floor,
                "min_sharpe_floor": self._active_sharpe_floor,
                "coverage_cap": self._active_coverage_cap,
                "hurst_exponent": self._derived_thresholds.hurst_exponent,
                "hurst_cv": self._derived_thresholds.hurst_cv,
                "hurst_estimator": self._derived_thresholds.hurst_estimator,
                "bah_sharpe_5pct": self._derived_thresholds.bah_sharpe_5pct,
                "empirical_2sigma_coverage": self._derived_thresholds.empirical_2sigma_coverage,
            },
            all_trials=self._all_trials,
        )

    def _objective(
        self,
        trial: optuna.Trial,
        df: pd.DataFrame,
        folds: List[WalkForwardSplit3Way],
        specs: List[Any],
        asset: str,
        timeframe: str,
        bars_per_year: float,
    ) -> Tuple[float, float, float]:
        """Optuna objective evaluating on the Validation fold."""
        # Worst-case sentinel for multi-objective: return dominated values
        # instead of TrialPruned (which causes shape mismatches in Optuna's
        # multi-objective TPE when all trials are pruned).
        _WORST = (0.0, 0.0, -100.0)

        params = self.search_space_builder.sample_params(trial, specs)
        
        fold_scores = []
        fold_benchmarks = []
        n_exceptions = 0
        
        for split in folds:
            train_df = df.iloc[split.train_start:split.train_end].copy()
            val_df = df.iloc[split.val_start:split.val_end].copy()
            
            try:
                score_tuple, bench = self._evaluate_fold(
                    train_df, val_df, params, asset, timeframe, bars_per_year
                )
            except Exception:
                logger.debug(
                    f"Trial {trial.number} fold {split.fold_id}: exception during evaluation",
                    exc_info=True,
                )
                n_exceptions += 1
                if n_exceptions > self.config.max_failed_folds:
                    return _WORST
                continue

            # Gate/constraint failures don't kill the trial — only exclude the
            # fold from score aggregation.  Optuna sees the trial's aggregated
            # score over passing folds (or _WORST if none pass).
            if not bench.passed_residual_gate or not bench.passed_confidence_constraint:
                continue

            fold_scores.append(score_tuple)
            fold_benchmarks.append(bench)

        if not fold_scores:
            trial.set_user_attr("constraints", [1.0, 1.0])
            return _WORST

        # Worst-case percentile aggregation across folds
        agg_score = tuple(
            float(x) for x in np.percentile(fold_scores, self.config.worst_case_percentile, axis=0)
        )

        # Cap band_coverage objective using data-derived threshold
        coverage_cap = self._active_coverage_cap
        agg_score = (
            agg_score[0],
            min(agg_score[1], coverage_cap),
            agg_score[2],
        )
        
        # Aggregate benchmarks for metadata tracking
        agg_bench = self._aggregate_benchmarks(fold_benchmarks)

        # Set Optuna constraints using data-derived floors
        # (negative = feasible, positive = violated)
        trial.set_user_attr("constraints", [
            -(agg_score[0] - self._active_direction_floor),
            -(agg_score[2] - self._active_sharpe_floor),
        ])

        trial_result = RegressionTrialResult(
            trial_id=trial.number,
            params=params,
            objective_values=agg_score,
            benchmark_results=agg_bench,
            passed_gate=agg_bench.passed_residual_gate,
            passed_constraint=agg_bench.passed_confidence_constraint,
            fold_results=fold_benchmarks,
        )

        with self._trials_lock:
            self._all_trials.append(trial_result)

        logger.debug(
            f"Trial {trial.number}: dir={agg_score[0]:.3f} cov={agg_score[1]:.3f} "
            f"sharpe={agg_score[2]:.3f} dd={agg_bench.max_drawdown:.4f} "
            f"folds={len(fold_scores)}/{len(folds)}"
        )

        return agg_score

    def _evaluate_fold(
        self,
        train_df: pd.DataFrame,
        eval_df: pd.DataFrame,
        params: dict,
        asset: str,
        timeframe: str,
        bars_per_year: float,
    ) -> Tuple[Tuple[float, float, float], RegressionBenchmarkResults]:
        """Fit on train, score on eval."""
        t0 = time.time()
        pipeline, config = self.pipeline_factory(params, asset, timeframe)

        # Warmup: fit the pipeline on training data (stateless — resets internally)
        pipeline.compute_series(PipelineRequest(
            df=train_df, asset=asset, timeframe=timeframe, mode="fit_series", config=config
        ))
        
        # Eval: pipeline resets and re-fits on eval data (no state leakage)
        results = pipeline.compute_series(PipelineRequest(
            df=eval_df, asset=asset, timeframe=timeframe, mode="fit_series", config=config
        ))

        closes = eval_df["close"].values
        elapsed_ms = (time.time() - t0) * 1000

        if not results or len(results) < self.config.min_valid_results:
            return (0.0, 0.0, 0.0), RegressionBenchmarkResults(
                passed_residual_gate=False, passed_confidence_constraint=False,
            )

        bench = self._compute_benchmarks(results, closes, elapsed_ms, bars_per_year)
        
        score_tuple = (
            bench.weighted_direction_score,
            bench.band_coverage_pct,
            bench.confidence_sharpe,
        )
        return score_tuple, bench

    def _evaluate_oos(
        self,
        params: dict,
        df: pd.DataFrame,
        folds: List[WalkForwardSplit3Way],
        asset: str,
        timeframe: str,
        bars_per_year: float,
    ) -> RegressionBenchmarkResults:
        """Final Out-Of-Sample evaluation on test_df across all folds."""
        fold_benchmarks = []
        for split in folds:
            warmup_df = df.iloc[split.train_start:split.val_end].copy()
            test_df = df.iloc[split.test_start:split.test_end].copy()
            
            _, bench = self._evaluate_fold(
                warmup_df, test_df, params, asset, timeframe, bars_per_year
            )
            fold_benchmarks.append(bench)
            
        return self._aggregate_benchmarks(fold_benchmarks)

    def _compute_benchmarks(
        self,
        results: List[RegressionResult],
        closes: np.ndarray,
        elapsed_ms: float,
        bars_per_year: float,
    ) -> RegressionBenchmarkResults:
        """Execute the pure float benchmark suite (single extraction)."""
        arrays = extract_result_arrays(results, closes)
        turnover = float(arrays.get("turnover_rate", 0.0))

        d_acc = direction_accuracy.compute(
            results, closes, 
            horizons=self.config.direction_horizons,
            horizon_weights=self.config.direction_horizon_weights,
            arrays=arrays,
        )
        b_cal = band_calibration.compute(results, closes, arrays=arrays)
        r_qual = residual_quality.compute(
            results, closes, min_dw=self.config.min_durbin_watson, arrays=arrays,
        )
        c_corr = confidence_correlation.compute(
            results, closes, min_rho=self.config.min_confidence_rho, arrays=arrays,
        )
        s_util = strategy_utility.compute(
            results, closes, bars_per_year=bars_per_year, arrays=arrays,
        )

        return RegressionBenchmarkResults(
            direction_accuracy_4bar=d_acc["direction_accuracy_4bar"],
            direction_accuracy_12bar=d_acc["direction_accuracy_12bar"],
            direction_accuracy_24bar=d_acc["direction_accuracy_24bar"],
            weighted_direction_score=d_acc["weighted_direction_score"],
            band_coverage_pct=b_cal["band_coverage_pct"],
            band_width_stability=b_cal["band_width_stability"],
            confidence_sharpe=s_util["confidence_sharpe"],
            bah_sharpe=s_util["bah_sharpe"],
            sharpe_improvement=s_util["sharpe_improvement"],
            max_drawdown=s_util["max_drawdown"],
            durbin_watson=r_qual["durbin_watson"],
            passed_residual_gate=r_qual["passed_residual_gate"],
            confidence_return_spearman=c_corr["confidence_return_spearman"],
            passed_confidence_constraint=c_corr["passed_confidence_constraint"],
            computation_time_ms=elapsed_ms,
            n_bars=len(closes),
            n_valid_results=len(arrays["indices"]),
            turnover_rate=turnover,
        )

    def _aggregate_benchmarks(self, folds: List[RegressionBenchmarkResults]) -> RegressionBenchmarkResults:
        """Average benchmark metrics across folds."""
        if not folds:
            return RegressionBenchmarkResults()

        d = {}
        for k in folds[0].__dataclass_fields__:
            vals = [getattr(f, k) for f in folds]
            if isinstance(vals[0], bool):
                d[k] = all(vals)
            elif isinstance(vals[0], (int, float)):
                d[k] = float(np.mean(vals))
            else:
                d[k] = vals[0]
        return RegressionBenchmarkResults(**d)
