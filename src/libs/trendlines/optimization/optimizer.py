"""Trendlines Hyperparameter Optimizer.

Uses Optuna (Bayesian TPE) to optimize 5 continuous params + categorical
component params per asset per timeframe:

  interaction_tolerance_atr, asymmetry_threshold,
  convergence_rate_threshold, wick_rejection_ratio, squeeze_threshold
  + extractor left/right windows, fitter pivot window

Objective: 5-tier weighted composite with Tier 3 gate + Tier 4 constraint.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from app.trendlines.optimization.benchmarks import (
    fold_stability,
    longevity,
    penetration_gate,
    pivot_density,
    touch_accuracy,
)
from app.trendlines.optimization.models import (
    TrendlinesBenchmarkResults,
    TrendlinesOptimizationConfig,
    TrendlinesOptimizationResult,
    TrendlinesTrialResult,
)
from app.trendlines.optimization.walk_forward import WalkForwardValidator

try:
    import optuna
    from optuna.samplers import CmaEsSampler, RandomSampler, TPESampler
    from optuna.pruners import HyperbandPruner, MedianPruner

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False

logger = logging.getLogger("app.trendlines.optimization")


def _default_pipeline_factory(
    params: dict,
    asset: str,
    timeframe: str,
):
    """Run trendline pipeline with the given trial params and return fit result + pivots."""
    from app.trendlines.workflows.pipeline.evaluation import (
        run_pipeline_with_params,
    )
    from app.trendlines import build_extractor
    from app.trendlines.workflows.pipeline.temporal_spec import resolve_trendlines_workflow_config
    from app.trendlines import TrendlinePipelineConfig

    def run(train_df: pd.DataFrame):
        fit_result = run_pipeline_with_params(train_df, asset, timeframe, params)

        # Extract pivot count
        config = resolve_trendlines_workflow_config(params) or TrendlinePipelineConfig()
        extractor = build_extractor(config.extractor, **config.extractor_params)
        lookback_bars = params.get("lookback_bars")
        if lookback_bars is not None:
            pivot_df = train_df.tail(max(int(lookback_bars), 1))
        else:
            pivot_df = train_df
        pivots = extractor.extract(pivot_df)
        n_pivots = pivots.n_highs + pivots.n_lows

        return fit_result, n_pivots

    return run


class TrendlinesOptimizer:
    """Bayesian optimizer for trendline pipeline parameters.

    Usage
    -----
    config = TrendlinesOptimizationConfig(n_trials=50)
    optimizer = TrendlinesOptimizer(config)
    result = optimizer.optimize(df, asset="BTCUSDT", timeframe="1h")
    result.apply_to_config("app/trendlines/config/trendlines.yaml")
    """

    def __init__(
        self,
        config: Optional[TrendlinesOptimizationConfig] = None,
        pipeline_factory: Optional[Callable] = None,
    ):
        if not OPTUNA_AVAILABLE:
            raise ImportError("Optuna required: pip install optuna")
        self.config = config or TrendlinesOptimizationConfig()
        self.pipeline_factory = pipeline_factory or _default_pipeline_factory
        self._walk_forward = WalkForwardValidator(
            train_bars=self.config.train_bars,
            test_bars=self.config.test_bars,
            step_bars=self.config.step_bars,
            purge_bars=self.config.purge_bars,
            min_train_bars=self.config.min_train_bars,
        )
        self._all_trials: List[TrendlinesTrialResult] = []

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
    ) -> TrendlinesOptimizationResult:
        """Run full Bayesian optimization and return best result."""
        n_trials = n_trials or self.config.n_trials
        timeout_sec = timeout or self.config.timeout_seconds
        self._all_trials = []

        n_folds = self._walk_forward.n_folds(len(df))
        logger.info(
            "Starting trendlines optimization: %s %s | %d trials | %d folds | %d bars",
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

        return TrendlinesOptimizationResult(
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
        fold_benchmarks: List[TrendlinesBenchmarkResults] = []

        for split, train_df, test_df in self._walk_forward.iterate_splits(df):
            score, bench = self._evaluate_fold(train_df, test_df, params, asset, timeframe)
            fold_scores.append(score)
            fold_benchmarks.append(bench)

        # Tier 5: Fold stability computed across all folds
        stab = fold_stability.compute(fold_scores)

        mean_score = float(np.mean(fold_scores)) if fold_scores else 0.0

        # Add stability bonus to the mean score
        w = self.config.weights
        stability_bonus = w.fold_stability * stab["stability_score"]
        final_score = mean_score + stability_bonus

        agg_bench = self._aggregate_benchmarks(fold_benchmarks)
        agg_bench.fitness_cv = stab["fitness_cv"]
        agg_bench.stability_score = stab["stability_score"]
        agg_bench.n_folds = len(fold_scores)

        trial_result = TrendlinesTrialResult(
            trial_id=trial.number,
            params=params,
            objective_value=final_score,
            benchmark_results=agg_bench,
            passed_gate=agg_bench.passed_penetration_gate,
            passed_constraint=agg_bench.passed_pivot_constraint,
            fold_results=fold_benchmarks,
        )
        self._all_trials.append(trial_result)
        return final_score

    def _sample_params(self, trial: "optuna.Trial") -> dict:
        cfg = self.config
        params = {
            # 5 continuous optimizable params
            "interaction_tolerance_atr": trial.suggest_float(
                "interaction_tolerance_atr", *cfg.interaction_tolerance_atr,
            ),
            "asymmetry_threshold": trial.suggest_float(
                "asymmetry_threshold", *cfg.asymmetry_threshold,
            ),
            "convergence_rate_threshold": trial.suggest_float(
                "convergence_rate_threshold", *cfg.convergence_rate_threshold,
            ),
            "wick_rejection_ratio": trial.suggest_float(
                "wick_rejection_ratio", *cfg.wick_rejection_ratio,
            ),
            "squeeze_threshold": trial.suggest_float(
                "squeeze_threshold", *cfg.squeeze_threshold,
            ),
            # Categorical component params
            "left_window": trial.suggest_categorical(
                "left_window", list(cfg.extractor_left_windows),
            ),
            "right_window": trial.suggest_categorical(
                "right_window", list(cfg.extractor_right_windows),
            ),
            "pivot_window": trial.suggest_categorical(
                "pivot_window", list(cfg.fitter_pivot_windows),
            ),
        }
        # Lookback bars as fraction of train window
        if hasattr(cfg, "lookback_fractions") and cfg.lookback_fractions:
            lb_frac = trial.suggest_categorical(
                "lookback_fraction", list(cfg.lookback_fractions),
            )
            params["lookback_fraction"] = lb_frac
        return params

    def _evaluate_fold(
        self,
        train_df: pd.DataFrame,
        test_df: pd.DataFrame,
        params: dict,
        asset: str,
        timeframe: str,
    ) -> tuple:
        """Run pipeline on train_df, evaluate on test_df."""
        t0 = time.time()
        cfg = self.config

        # Resolve lookback_fraction → lookback_bars
        resolved_params = dict(params)
        lb_frac = resolved_params.pop("lookback_fraction", None)
        if lb_frac is not None and lb_frac < 1.0:
            resolved_params["lookback_bars"] = int(len(train_df) * lb_frac)

        # Inject fitter from config (default: ensemble)
        resolved_params.setdefault("fitter", cfg.fitter)

        try:
            runner = self.pipeline_factory(resolved_params, asset, timeframe)
            fit_result, n_pivots = runner(train_df)
        except Exception as exc:
            logger.debug("Fold pipeline failed: %s", exc)
            return 0.0, TrendlinesBenchmarkResults()

        if not fit_result.is_valid:
            return 0.0, TrendlinesBenchmarkResults()

        lines = fit_result.support_lines + fit_result.resistance_lines

        # Determine fit window bars for projection
        lookback_bars = resolved_params.get("lookback_bars")
        if lookback_bars is not None:
            fit_bars = min(len(train_df), max(int(lookback_bars), 1))
        else:
            fit_bars = len(train_df)

        elapsed_ms = (time.time() - t0) * 1000
        return self._compute_fold_score(
            lines, test_df, n_pivots, fit_bars, elapsed_ms,
        )

    def _compute_fold_score(
        self,
        lines: list,
        test_df: pd.DataFrame,
        n_pivots: float,
        fit_window_bars: int,
        elapsed_ms: float = 0.0,
    ) -> tuple:
        """Compute composite score for one fold.

        score = (w1·longevity + w2·touch_accuracy)
                × gate_mult(pen_rate)
                × constraint_mult(pivot_score)
        """
        cfg = self.config
        w = cfg.weights

        # Tier 1: Longevity
        t1 = longevity.compute(
            lines, test_df, fit_window_bars,
            slope_tolerance=cfg.slope_tolerance,
            consecutive_penetration_bars=cfg.consecutive_penetration_bars,
            min_tolerance_atr_frac=cfg.min_tolerance_atr_frac,
        )

        # Tier 2: Touch Accuracy
        t2 = touch_accuracy.compute(
            lines, test_df, fit_window_bars,
            slope_tolerance=cfg.slope_tolerance,
            forward_lookahead_bars=cfg.forward_lookahead_bars,
            min_tolerance_atr_frac=cfg.min_tolerance_atr_frac,
        )

        # Tier 3: Penetration Gate
        t3 = penetration_gate.compute(
            lines, test_df, fit_window_bars,
            slope_tolerance=cfg.slope_tolerance,
            consecutive_penetration_bars=cfg.consecutive_penetration_bars,
            max_penetration_rate=cfg.max_penetration_rate,
            min_tolerance_atr_frac=cfg.min_tolerance_atr_frac,
        )
        gate_mult = penetration_gate.gate_penalty(
            t3["mean_pen_rate"],
            threshold=cfg.max_penetration_rate,
            penalty_factor=cfg.penetration_gate_penalty,
            soft=cfg.soft_gate,
        )

        # Tier 4: Pivot Density Constraint
        t4 = pivot_density.compute(
            n_pivots,
            fit_window_bars,
            density_min=cfg.density_min,
            density_optimal_lo=cfg.density_optimal_lo,
            density_optimal_hi=cfg.density_optimal_hi,
            min_pivot_score=cfg.min_pivot_score,
        )
        constraint_mult = pivot_density.constraint_penalty(
            t4["pivot_score"],
            min_score=cfg.min_pivot_score,
            penalty=cfg.pivot_constraint_penalty,
        )

        # Line count penalty (within longevity tier)
        n_lines = t1["n_lines"]
        if n_lines == 0:
            line_penalty = cfg.line_count_penalty_factor
        elif n_lines > cfg.line_count_penalty_threshold:
            line_penalty = max(
                0.3,
                1.0 - (n_lines - cfg.line_count_penalty_threshold) * cfg.line_count_penalty_factor,
            )
        else:
            line_penalty = 1.0

        # Composite (fold stability added at trial level, not fold level)
        floor = 0.01
        score = (
            w.longevity * t1["mean_longevity"] * line_penalty
            + w.touch_accuracy * max(t2["touch_accuracy"], floor)
        ) * gate_mult * constraint_mult

        # Raw fitness for fold-stability computation
        raw_fitness = t1["mean_longevity"] * (1.0 - t3["mean_pen_rate"]) * max(t2["touch_accuracy"], floor)

        bench = TrendlinesBenchmarkResults(
            mean_longevity=t1["mean_longevity"],
            n_lines=t1["n_lines"],
            touch_accuracy=t2["touch_accuracy"],
            total_touches=t2["total_touches"],
            total_hits=t2["total_hits"],
            mean_pen_rate=t3["mean_pen_rate"],
            passed_penetration_gate=t3["passed_gate"],
            mean_pivots=float(n_pivots),
            pivot_density=float(t4["density"]),
            pivot_score=t4["pivot_score"],
            passed_pivot_constraint=t4["passed_constraint"],
            fitness=raw_fitness,
            computation_time_ms=elapsed_ms,
            n_bars=len(test_df),
        )
        return float(score), bench

    def _compute_all_benchmarks(
        self,
        df: pd.DataFrame,
        params: dict,
        asset: str,
        timeframe: str,
    ) -> TrendlinesBenchmarkResults:
        """Compute full benchmarks on entire dataset for best params."""
        fold_scores = []
        fold_benchmarks = []
        try:
            for split, train_df, test_df in self._walk_forward.iterate_splits(df):
                score, bench = self._evaluate_fold(
                    train_df, test_df, params, asset, timeframe,
                )
                fold_scores.append(score)
                fold_benchmarks.append(bench)
        except Exception as exc:
            logger.warning("Final benchmark computation failed: %s", exc)
            return TrendlinesBenchmarkResults()

        if not fold_benchmarks:
            return TrendlinesBenchmarkResults()

        agg = self._aggregate_benchmarks(fold_benchmarks)
        stab = fold_stability.compute(fold_scores)
        agg.fitness_cv = stab["fitness_cv"]
        agg.stability_score = stab["stability_score"]
        agg.n_folds = len(fold_scores)
        agg.n_bars = len(df)
        return agg

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
    def _aggregate_benchmarks(
        folds: List[TrendlinesBenchmarkResults],
    ) -> TrendlinesBenchmarkResults:
        """Average metrics across folds with robust gate aggregation.

        For boolean fields (passed_penetration_gate, passed_pivot_constraint),
        uses a two-part robust criterion instead of unanimous ``all()``:
        1. Pass-rate: ≥ gate_pass_ratio of folds must pass individually
        2. Tail-risk: worst-percentile pen_rate must be below tail threshold

        This prevents a single volatile fold from killing the entire trial while
        still catching setups that hide catastrophic folds behind a majority.
        """
        if not folds:
            return TrendlinesBenchmarkResults()
        fields = TrendlinesBenchmarkResults.__dataclass_fields__.keys()
        agg = {}
        for f in fields:
            vals = [getattr(b, f) for b in folds]
            if isinstance(vals[0], bool):
                # Robust aggregation: ≥70% of folds must pass
                agg[f] = (sum(vals) / len(vals)) >= 0.7
            elif isinstance(vals[0], (int, float)):
                finite = [v for v in vals if np.isfinite(v)]
                agg[f] = float(np.mean(finite)) if finite else 0.0
            else:
                agg[f] = vals[0]

        # Tail-risk check for penetration gate
        pen_rates = [b.mean_pen_rate for b in folds if np.isfinite(b.mean_pen_rate)]
        if pen_rates:
            p90_pen = float(np.percentile(pen_rates, 90))
            # Override gate pass if tail is too bad (worst 10% of folds)
            if p90_pen > 0.6:
                agg["passed_penetration_gate"] = False

        return TrendlinesBenchmarkResults(**agg)
