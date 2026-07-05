"""Data models for trendlines optimization framework.

5-parameter optimization of the trendlines pipeline:
  interaction_tolerance_atr, asymmetry_threshold,
  convergence_rate_threshold, wick_rejection_ratio, squeeze_threshold
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Benchmark Results (all 5 tiers in one flat struct)
# ---------------------------------------------------------------------------

@dataclass
class TrendlinesBenchmarkResults:
    """Complete benchmark output from a single walk-forward fold evaluation.

    Tiers 1, 2, 5 contribute weighted scores to the composite objective.
    Tier 3 (penetration rate) acts as a multiplicative GATE.
    Tier 4 (pivot density) acts as a multiplicative CONSTRAINT.
    """

    # Tier 1: Longevity (35% weight)
    mean_longevity: float = 0.0       # mean trendline survival ratio [0, 1]
    n_lines: int = 0                  # total lines evaluated

    # Tier 2: Touch Accuracy (25% weight)
    touch_accuracy: float = 0.0       # touch-reaction prediction accuracy [0, 1]
    total_touches: int = 0
    total_hits: int = 0

    # Tier 3: Penetration Rate (GATE — not weighted)
    mean_pen_rate: float = 1.0        # mean penetration rate [0, 1]; lower is better
    passed_penetration_gate: bool = False

    # Tier 4: Pivot Density (CONSTRAINT — not weighted)
    mean_pivots: float = 0.0
    std_pivots: float = 0.0
    pivot_density: float = 0.0        # pivots per 100 bars
    pivot_score: float = 0.0          # tent score [0, 1]
    passed_pivot_constraint: bool = False

    # Tier 5: Fold Stability (15% weight)
    fitness_cv: float = 1.0           # coefficient of variation of fold fitness
    stability_score: float = 0.0      # 1 - CV, clamped to [0, 1]

    # Composite
    fitness: float = 0.0              # longevity*(1-pen)*touch_acc (raw, pre-tiered)

    # Meta
    computation_time_ms: float = 0.0
    n_bars: int = 0
    n_folds: int = 0

    def to_dict(self) -> Dict[str, Any]:
        import numpy as np
        d = {}
        for k in self.__dataclass_fields__:
            v = getattr(self, k)
            if isinstance(v, (np.bool_, np.generic)):
                v = v.item()
            d[k] = v
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TrendlinesBenchmarkResults":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Optimization Weights
# ---------------------------------------------------------------------------

@dataclass
class TrendlinesOptimizationWeights:
    """Tier weights for composite objective.

    Tier 3 (Penetration) is a GATE — not weighted, applied multiplicatively.
    Tier 4 (Pivot Density) is a CONSTRAINT — not weighted, applied multiplicatively.
    Weighted tiers should sum to ~0.75.
    """
    longevity: float = 0.35
    touch_accuracy: float = 0.25
    fold_stability: float = 0.15

    def validate(self) -> None:
        total = self.longevity + self.touch_accuracy + self.fold_stability
        if abs(total - 0.75) > 0.02:
            raise ValueError(f"Weighted tiers should sum to ~0.75, got {total:.3f}")


# ---------------------------------------------------------------------------
# Optimization Config (search space + run settings)
# ---------------------------------------------------------------------------

@dataclass
class TrendlinesOptimizationConfig:
    """Full configuration for one trendlines optimization run.

    Search space for the 5 continuous optimizable params is defined as
    ``(min, max)`` tuples.  Component grid params (extractor/fitter) are
    lists of categorical values.
    """

    # --- Search space: 5 continuous optimizable params ---
    interaction_tolerance_atr: Tuple[float, float] = (0.10, 0.50)
    asymmetry_threshold: Tuple[float, float] = (0.10, 0.60)
    convergence_rate_threshold: Tuple[float, float] = (0.05, 0.50)
    wick_rejection_ratio: Tuple[float, float] = (0.20, 0.80)
    squeeze_threshold: Tuple[float, float] = (1.0, 6.0)

    # --- Search space: categorical component params ---
    extractor_left_windows: Tuple[int, ...] = (3, 5, 7, 10)
    extractor_right_windows: Tuple[int, ...] = (3, 5, 7, 10)
    fitter_pivot_windows: Tuple[int, ...] = (2, 3, 5)

    # --- Run settings ---
    n_trials: int = 50
    timeout_seconds: int = 1800
    n_jobs: int = 1
    sampler: str = "tpe"
    pruner: str = "median"

    # --- Gate: Tier 3 Penetration Rate ---
    # Threshold set to 0.55 to accommodate the structural 0.50 artifact:
    # with 2 lines (1 support + 1 resistance), if one holds (pen≈0) and
    # the other fails in a trending fold (pen≈1), the mean is exactly 0.50.
    # A threshold of 0.55 lets these "one-good-line" folds pass the gate.
    max_penetration_rate: float = 0.55
    penetration_gate_penalty: float = 3.0
    soft_gate: bool = True

    # --- Constraint: Tier 4 Pivot Density (density = pivots/100bars) ---
    density_min: float = 2.0
    density_optimal_lo: float = 8.0
    density_optimal_hi: float = 25.0
    min_pivot_score: float = 0.3
    pivot_constraint_penalty: float = 0.3

    # --- Search space: lookback_bars (fraction of train window) ---
    lookback_fractions: Tuple[float, ...] = (0.3, 0.5, 0.7, 1.0)

    # --- Fitter selection ---
    fitter: str = "ensemble"

    # --- Walk-forward ---
    train_bars: int = 2160
    test_bars: int = 720
    step_bars: int = 720
    purge_bars: int = 24
    min_train_bars: int = 1440

    # --- Weights ---
    weights: TrendlinesOptimizationWeights = field(
        default_factory=TrendlinesOptimizationWeights
    )

    # --- Fitness protocol (from trendlines.yaml protocol section) ---
    slope_tolerance: float = 0.25
    min_tolerance_atr_frac: float = 0.1
    consecutive_penetration_bars: int = 3
    forward_lookahead_bars: int = 3
    line_count_penalty_threshold: int = 6
    line_count_penalty_factor: float = 0.1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interaction_tolerance_atr": self.interaction_tolerance_atr,
            "asymmetry_threshold": self.asymmetry_threshold,
            "convergence_rate_threshold": self.convergence_rate_threshold,
            "wick_rejection_ratio": self.wick_rejection_ratio,
            "squeeze_threshold": self.squeeze_threshold,
            "extractor_left_windows": self.extractor_left_windows,
            "extractor_right_windows": self.extractor_right_windows,
            "fitter_pivot_windows": self.fitter_pivot_windows,
            "n_trials": self.n_trials,
            "timeout_seconds": self.timeout_seconds,
            "sampler": self.sampler,
            "pruner": self.pruner,
        }


# ---------------------------------------------------------------------------
# Trial Result
# ---------------------------------------------------------------------------

@dataclass
class TrendlinesTrialResult:
    """Single Optuna trial result with per-fold breakdown."""
    trial_id: int
    params: Dict[str, Any]
    objective_value: float
    benchmark_results: TrendlinesBenchmarkResults
    passed_gate: bool
    passed_constraint: bool
    fold_results: List[TrendlinesBenchmarkResults] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "params": self.params,
            "objective_value": self.objective_value,
            "benchmark_results": self.benchmark_results.to_dict(),
            "passed_gate": self.passed_gate,
            "passed_constraint": self.passed_constraint,
            "fold_results": [f.to_dict() for f in self.fold_results],
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Optimization Result
# ---------------------------------------------------------------------------

@dataclass
class TrendlinesOptimizationResult:
    """Full result from one optimization run."""
    asset: str
    timeframe: str
    best_params: Dict[str, Any]
    best_objective: float
    best_benchmarks: TrendlinesBenchmarkResults
    n_trials_passed_gate: int
    n_trials_total: int
    total_time_seconds: float
    config: TrendlinesOptimizationConfig
    all_trials: List[TrendlinesTrialResult] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def save(self, path: str) -> None:
        import numpy as np

        class _NumpyEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, (np.bool_,)):
                    return bool(obj)
                if isinstance(obj, (np.integer,)):
                    return int(obj)
                if isinstance(obj, (np.floating,)):
                    return float(obj)
                if isinstance(obj, np.ndarray):
                    return obj.tolist()
                return super().default(obj)

        data = {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "best_params": self.best_params,
            "best_objective": self.best_objective,
            "best_benchmarks": self.best_benchmarks.to_dict(),
            "n_trials_passed_gate": self.n_trials_passed_gate,
            "n_trials_total": self.n_trials_total,
            "total_time_seconds": self.total_time_seconds,
            "config": self.config.to_dict(),
            "timestamp": self.timestamp.isoformat(),
            "all_trials": [t.to_dict() for t in self.all_trials],
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2, cls=_NumpyEncoder)

    @classmethod
    def load(cls, path: str) -> "TrendlinesOptimizationResult":
        with open(path) as f:
            data = json.load(f)
        best_benchmarks = TrendlinesBenchmarkResults.from_dict(data["best_benchmarks"])
        trials = []
        for t in data.get("all_trials", []):
            br = TrendlinesBenchmarkResults.from_dict(t["benchmark_results"])
            fold_results = [
                TrendlinesBenchmarkResults.from_dict(fr)
                for fr in t.get("fold_results", [])
            ]
            trials.append(TrendlinesTrialResult(
                trial_id=t["trial_id"],
                params=t["params"],
                objective_value=t["objective_value"],
                benchmark_results=br,
                passed_gate=t["passed_gate"],
                passed_constraint=t.get("passed_constraint", True),
                fold_results=fold_results,
                timestamp=datetime.fromisoformat(t["timestamp"]),
            ))
        cfg_d = data.get("config", {})
        config = TrendlinesOptimizationConfig(
            n_trials=cfg_d.get("n_trials", 50),
            timeout_seconds=cfg_d.get("timeout_seconds", 1800),
            sampler=cfg_d.get("sampler", "tpe"),
            pruner=cfg_d.get("pruner", "median"),
        )
        return cls(
            asset=data["asset"],
            timeframe=data["timeframe"],
            best_params=data["best_params"],
            best_objective=data["best_objective"],
            best_benchmarks=best_benchmarks,
            n_trials_passed_gate=data["n_trials_passed_gate"],
            n_trials_total=data["n_trials_total"],
            total_time_seconds=data.get("total_time_seconds", 0.0),
            config=config,
            all_trials=trials,
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )

    def apply_to_config(self, yaml_path: str) -> None:
        """Write best optimizable params to trendlines.yaml per-asset/TF section."""
        import yaml

        with open(yaml_path) as f:
            cfg = yaml.safe_load(f)

        optimizable_keys = {
            "interaction_tolerance_atr",
            "asymmetry_threshold",
            "convergence_rate_threshold",
            "wick_rejection_ratio",
            "squeeze_threshold",
            "lookback_fraction",
        }
        overrides = {
            k: round(v, 6) if isinstance(v, float) else v
            for k, v in self.best_params.items()
            if k in optimizable_keys
        }

        if not overrides:
            return

        assets = cfg.setdefault("assets", {})
        asset_block = assets.setdefault(self.asset, {})
        timeframes = asset_block.setdefault("timeframes", {})
        tf_block = timeframes.setdefault(self.timeframe, {})
        tf_block.update(overrides)

        with open(yaml_path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
