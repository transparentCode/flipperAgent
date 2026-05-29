"""
Meta-Filter selection logic for MOTPE Pareto fronts.

Two strategies:
  - MetaFilterSelector: Orthogonal single-metric filter (legacy, default=max_drawdown).
  - HarmonicStabilitySelector: Harmonic-mean balance × fold-stability (recommended).
"""

from __future__ import annotations

import logging
import statistics
from typing import Dict, List, Optional, Tuple

from app.regression.optimization.models import (
    RegressionBenchmarkResults,
    RegressionTrialResult,
)

logger = logging.getLogger("app.regression.optimization")

# Pre-compute valid metric names from the dataclass fields
_VALID_METRICS = frozenset(RegressionBenchmarkResults.__dataclass_fields__.keys())

# Epsilon for numerical stability
_EPS = 1e-10


class MetaFilterSelector:
    """
    Evaluates a set of Pareto-optimal configurations on the Validation folds
    and selects the single best candidate based on an orthogonal metric.
    """

    def __init__(self, metric: str = "max_drawdown", minimize: bool = True):
        if metric not in _VALID_METRICS:
            raise ValueError(
                f"Invalid meta_filter_metric '{metric}'. "
                f"Must be one of: {sorted(_VALID_METRICS)}"
            )
        self.metric = metric
        self.minimize = minimize

    def select_best_candidate(
        self,
        pareto_front: List[RegressionTrialResult],
    ) -> RegressionTrialResult:
        """
        Selects the best trial from the Pareto front based on the meta-filter metric.
        Assumes that the fold_results stored in the trials correspond to the Validation phase.
        """
        if not pareto_front:
            raise ValueError("Pareto front is empty.")

        if len(pareto_front) == 1:
            return pareto_front[0]

        best_trial = None
        best_score = float('inf') if self.minimize else float('-inf')

        for trial in pareto_front:
            # We aggregate the metric across all folds for this trial.
            # Using worst-case (max drawdown) across all folds.
            if not trial.fold_results:
                continue

            scores = [getattr(fr, self.metric, 0.0) for fr in trial.fold_results]
            
            # For drawdown, the worst-case fold is the maximum drawdown.
            # For other metrics it depends.
            if self.minimize:
                agg_score = max(scores)
            else:
                agg_score = min(scores)

            if self.minimize:
                if agg_score < best_score:
                    best_score = agg_score
                    best_trial = trial
            else:
                if agg_score > best_score:
                    best_score = agg_score
                    best_trial = trial

        return best_trial or pareto_front[0]


class HarmonicStabilitySelector:
    """
    Selects the Pareto candidate with the most balanced and fold-stable
    performance across all 3 primary objectives.

    Algorithm:
      0. Quality-floor filter: reject Pareto candidates below absolute thresholds
      1. Rank-normalize each objective across the Pareto front → [0, 1]
      2. Harmonic mean of normalized scores (punishes any single weak axis)
      3. Fold-stability penalty: multiply by (1 - CV) where CV = coefficient
         of variation of the candidate's objective values across walk-forward folds
      4. Pick argmax(harmonic_mean × fold_stability)
    """

    # Default quality floors — override via constructor
    DEFAULT_QUALITY_FLOORS = {
        "weighted_direction_score": 0.50,
        "confidence_sharpe": 0.0,
    }

    def __init__(
        self,
        objectives: Tuple[str, ...] = (
            "weighted_direction_score",
            "band_coverage_pct",
            "confidence_sharpe",
        ),
        quality_floors: Optional[Dict[str, float]] = None,
    ):
        self.objectives = objectives
        self.quality_floors = quality_floors or dict(self.DEFAULT_QUALITY_FLOORS)

    def select_best_candidate(
        self,
        pareto_front: List[RegressionTrialResult],
    ) -> RegressionTrialResult:
        """Select the most balanced + stable candidate from the Pareto front."""
        if not pareto_front:
            raise ValueError("Pareto front is empty.")

        if len(pareto_front) == 1:
            return pareto_front[0]

        # Step 0: Quality-floor filter
        feasible = self._apply_quality_floors(pareto_front)
        if not feasible:
            logger.warning(
                f"No Pareto candidates passed quality floors "
                f"({self.quality_floors}) — falling back to full front "
                f"({len(pareto_front)} candidates)"
            )
            feasible = pareto_front

        n = len(feasible)
        if n == 1:
            logger.info(
                f"HarmonicStability selection: only 1 candidate passed quality floor, "
                f"best=trial_{feasible[0].trial_id}"
            )
            return feasible[0]

        # Step 1: Extract raw objective vectors and rank-normalize
        # objective_values are ordered same as self.objectives
        raw_scores = [trial.objective_values for trial in feasible]

        # Rank-normalize each dimension (higher is better for all 3)
        normalized = self._rank_normalize(raw_scores)

        # Step 2: Harmonic mean of normalized scores for each candidate
        harmonic_means = []
        for i in range(n):
            vals = normalized[i]
            # Clamp to avoid division by zero
            clamped = [max(v, _EPS) for v in vals]
            k = len(clamped)
            hm = k / sum(1.0 / v for v in clamped)
            harmonic_means.append(hm)

        # Step 3: Fold-stability penalty per candidate
        stability_scores = []
        for trial in feasible:
            stability_scores.append(self._fold_stability(trial))

        # Step 4: Composite score = harmonic_mean × fold_stability
        composite = [hm * fs for hm, fs in zip(harmonic_means, stability_scores)]

        best_idx = max(range(n), key=lambda i: composite[i])
        best = feasible[best_idx]

        logger.info(
            f"HarmonicStability selection: {len(pareto_front)} Pareto candidates, "
            f"{n} passed quality floor, "
            f"best=trial_{best.trial_id} "
            f"(harmonic={harmonic_means[best_idx]:.4f}, "
            f"stability={stability_scores[best_idx]:.4f}, "
            f"composite={composite[best_idx]:.4f})"
        )

        return best

    def _apply_quality_floors(
        self, candidates: List[RegressionTrialResult]
    ) -> List[RegressionTrialResult]:
        """Reject candidates below absolute quality thresholds."""
        feasible = []
        for trial in candidates:
            passed = True
            for metric, floor in self.quality_floors.items():
                val = getattr(trial.benchmark_results, metric, None)
                if val is not None and val < floor:
                    passed = False
                    break
            if passed:
                feasible.append(trial)
        return feasible

    def _rank_normalize(self, raw_scores: List[Tuple[float, ...]]) -> List[List[float]]:
        """Rank-percentile normalize each dimension across candidates."""
        n = len(raw_scores)
        if n == 1:
            return [[1.0] * len(raw_scores[0])]

        n_dims = len(raw_scores[0])
        normalized = [[0.0] * n_dims for _ in range(n)]

        for d in range(n_dims):
            # Sort indices by value in this dimension
            col = [(raw_scores[i][d], i) for i in range(n)]
            col.sort(key=lambda x: x[0])
            # Assign rank percentile
            for rank, (_, idx) in enumerate(col):
                normalized[idx][d] = (rank + 1) / n  # [1/n, 1.0]

        return normalized

    def _fold_stability(self, trial: RegressionTrialResult) -> float:
        """
        Compute fold stability as 1 - mean(CV) across objectives.
        CV = stdev/mean for each objective across fold_results.
        Returns value in (0, 1] — higher is more stable.
        """
        if not trial.fold_results or len(trial.fold_results) < 2:
            return 1.0  # Single fold — no variance info, assume stable

        cvs = []
        for obj_name in self.objectives:
            fold_values = [getattr(fr, obj_name, 0.0) for fr in trial.fold_results]
            mean_val = statistics.mean(fold_values)
            if abs(mean_val) < _EPS:
                cvs.append(1.0)  # Near-zero mean → treat as maximally unstable
                continue
            stdev_val = statistics.stdev(fold_values)
            cv = abs(stdev_val / mean_val)
            cvs.append(min(cv, 1.0))  # Cap at 1.0 to avoid negative stability

        mean_cv = statistics.mean(cvs)
        return max(1.0 - mean_cv, _EPS)  # Floor at epsilon
