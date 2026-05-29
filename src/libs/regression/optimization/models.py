"""
Data models for regression v2 MOTPE optimization framework.
Strictly decoupled from V1 scalar optimization.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import yaml
from pydantic import BaseModel, Field

from app.regression.optimization.constants import (
    DEFAULT_CONFIDENCE_HORIZON,
    DEFAULT_COVERAGE_CAP,
    DEFAULT_DIRECTION_HORIZON_WEIGHTS,
    DEFAULT_DIRECTION_HORIZONS,
    DEFAULT_MAX_FAILED_FOLDS,
    DEFAULT_MAX_TRAIN_RATIO,
    DEFAULT_META_FILTER_METRIC,
    DEFAULT_MIN_CONFIDENCE_RHO,
    DEFAULT_MIN_DIRECTION_FLOOR,
    DEFAULT_MIN_DURBIN_WATSON,
    DEFAULT_MIN_SHARPE_FLOOR,
    DEFAULT_MIN_TRAIN_BARS,
    DEFAULT_MIN_VALID_RESULTS,
    DEFAULT_N_JOBS,
    DEFAULT_N_TRIALS,
    DEFAULT_OBJECTIVES,
    DEFAULT_PARAM_BOUNDS,
    DEFAULT_PARAM_TYPES,
    DEFAULT_PURGE_BARS,
    DEFAULT_SEED,
    DEFAULT_STEP_BARS,
    DEFAULT_TEST_BARS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TRAIN_BARS,
    DEFAULT_VALIDATE_BARS,
    DEFAULT_WORST_CASE_PERCENTILE,
)


# ---------------------------------------------------------------------------
# Benchmark Results (Flat Vector)
# ---------------------------------------------------------------------------

@dataclass
class RegressionBenchmarkResults:
    """Complete benchmark output from a single walk-forward fold evaluation."""

    # Objective 1: Direction
    direction_accuracy_4bar: float = 0.0
    direction_accuracy_12bar: float = 0.0
    direction_accuracy_24bar: float = 0.0
    weighted_direction_score: float = 0.0

    # Objective 2: Band Calibration
    band_coverage_pct: float = 0.0
    band_width_stability: float = 0.0

    # Objective 3: Utility
    confidence_sharpe: float = 0.0
    bah_sharpe: float = 0.0
    sharpe_improvement: float = 0.0
    max_drawdown: float = 0.0

    # Gate / Constraints
    durbin_watson: float = 0.0
    passed_residual_gate: bool = False
    confidence_return_spearman: float = 0.0
    passed_confidence_constraint: bool = False

    # Meta
    computation_time_ms: float = 0.0
    n_bars: int = 0
    n_valid_results: int = 0
    turnover_rate: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-safe dict (cast numpy scalars to Python natives)."""
        import numpy as np

        d = {}
        for k in self.__dataclass_fields__:
            v = getattr(self, k)
            if isinstance(v, (np.bool_, np.generic)):
                v = v.item()
            d[k] = v
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RegressionBenchmarkResults":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Optimization Config
# ---------------------------------------------------------------------------

class MOTPEConfig(BaseModel):
    """Multi-Objective TPE (MOTPE) configuration."""
    objectives: List[str] = Field(
        default_factory=lambda: list(DEFAULT_OBJECTIVES),
        max_length=3,
        description="Exactly 3 objectives to optimize. Exceeding 3 destroys Pareto front quality."
    )
    meta_filter_metric: str = Field(
        default=DEFAULT_META_FILTER_METRIC,
        description="Orthogonal metric used to select the single best trial from the Pareto front."
    )
    meta_filter_strategy: str = Field(
        default="harmonic_stability",
        description="Selection strategy: 'harmonic_stability' (balanced + fold-stable) or 'orthogonal' (legacy single-metric filter)."
    )
    coverage_cap: float = Field(
        default=DEFAULT_COVERAGE_CAP,
        description="Soft ceiling on band_coverage_pct objective. Values above this are clamped."
    )
    min_direction_floor: float = Field(
        default=DEFAULT_MIN_DIRECTION_FLOOR,
        description="MOTPE constraint: weighted_direction_score must be >= this for feasibility."
    )
    min_sharpe_floor: float = Field(
        default=DEFAULT_MIN_SHARPE_FLOOR,
        description="MOTPE constraint: confidence_sharpe must be >= this for feasibility."
    )


class RegressionOptimizationConfig(BaseModel):
    """
    Full configuration for one regression MOTPE optimization run.
    """
    # --- Search space bounds ---
    param_bounds: Dict[str, Tuple[float, float]] = Field(
        default_factory=lambda: dict(DEFAULT_PARAM_BOUNDS),
    )
    param_types: Dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_PARAM_TYPES),
    )

    # --- Run settings ---
    n_trials: int = DEFAULT_N_TRIALS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    n_jobs: int = DEFAULT_N_JOBS
    seed: int = DEFAULT_SEED

    # --- MOTPE ---
    motpe: MOTPEConfig = Field(default_factory=MOTPEConfig)

    # --- Gate/Constraints ---
    min_durbin_watson: float = DEFAULT_MIN_DURBIN_WATSON
    min_confidence_rho: float = DEFAULT_MIN_CONFIDENCE_RHO

    # --- 3-Way Walk-forward ---
    train_bars: int = DEFAULT_TRAIN_BARS
    validate_bars: int = DEFAULT_VALIDATE_BARS
    test_bars: int = DEFAULT_TEST_BARS
    step_bars: int = DEFAULT_STEP_BARS
    purge_bars: int = DEFAULT_PURGE_BARS
    min_train_bars: int = DEFAULT_MIN_TRAIN_BARS

    # --- Direction accuracy horizons ---
    direction_horizons: Tuple[int, ...] = DEFAULT_DIRECTION_HORIZONS
    direction_horizon_weights: Tuple[float, ...] = DEFAULT_DIRECTION_HORIZON_WEIGHTS

    # --- Aggregation ---
    worst_case_percentile: int = DEFAULT_WORST_CASE_PERCENTILE
    min_valid_results: int = DEFAULT_MIN_VALID_RESULTS
    max_train_ratio: float = DEFAULT_MAX_TRAIN_RATIO
    max_failed_folds: int = DEFAULT_MAX_FAILED_FOLDS

    optimization_tier: str = "full"
    expanding_window: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "param_bounds": {k: list(v) for k, v in self.param_bounds.items()},
            "param_types": self.param_types,
            "n_trials": self.n_trials,
            "timeout_seconds": self.timeout_seconds,
            "n_jobs": self.n_jobs,
            "seed": self.seed,
            "motpe": {
                "objectives": self.motpe.objectives,
                "meta_filter_metric": self.motpe.meta_filter_metric,
                "meta_filter_strategy": self.motpe.meta_filter_strategy,
                "coverage_cap": self.motpe.coverage_cap,
                "min_direction_floor": self.motpe.min_direction_floor,
                "min_sharpe_floor": self.motpe.min_sharpe_floor,
            },
            "min_durbin_watson": self.min_durbin_watson,
            "min_confidence_rho": self.min_confidence_rho,
            "train_bars": self.train_bars,
            "validate_bars": self.validate_bars,
            "test_bars": self.test_bars,
            "step_bars": self.step_bars,
            "purge_bars": self.purge_bars,
            "min_train_bars": self.min_train_bars,
            "direction_horizons": list(self.direction_horizons),
            "direction_horizon_weights": list(self.direction_horizon_weights),
            "worst_case_percentile": self.worst_case_percentile,
            "min_valid_results": self.min_valid_results,
            "max_train_ratio": self.max_train_ratio,
            "max_failed_folds": self.max_failed_folds,
            "optimization_tier": self.optimization_tier,
            "expanding_window": self.expanding_window,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RegressionOptimizationConfig":
        bounds = d.get("param_bounds", {})
        param_bounds = {k: tuple(v) for k, v in bounds.items()} if bounds else {}

        motpe_d = d.get("motpe", {})
        motpe = MOTPEConfig(**motpe_d) if motpe_d else MOTPEConfig()

        return cls(
            param_bounds=param_bounds or dict(DEFAULT_PARAM_BOUNDS),
            param_types=d.get("param_types", dict(DEFAULT_PARAM_TYPES)),
            n_trials=d.get("n_trials", DEFAULT_N_TRIALS),
            timeout_seconds=d.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
            n_jobs=d.get("n_jobs", DEFAULT_N_JOBS),
            seed=d.get("seed", DEFAULT_SEED),
            motpe=motpe,
            min_durbin_watson=d.get("min_durbin_watson", DEFAULT_MIN_DURBIN_WATSON),
            min_confidence_rho=d.get("min_confidence_rho", DEFAULT_MIN_CONFIDENCE_RHO),
            train_bars=d.get("train_bars", DEFAULT_TRAIN_BARS),
            validate_bars=d.get("validate_bars", DEFAULT_VALIDATE_BARS),
            test_bars=d.get("test_bars", DEFAULT_TEST_BARS),
            step_bars=d.get("step_bars", DEFAULT_STEP_BARS),
            purge_bars=d.get("purge_bars", DEFAULT_PURGE_BARS),
            min_train_bars=d.get("min_train_bars", DEFAULT_MIN_TRAIN_BARS),
            direction_horizons=tuple(d.get("direction_horizons", DEFAULT_DIRECTION_HORIZONS)),
            direction_horizon_weights=tuple(d.get("direction_horizon_weights", DEFAULT_DIRECTION_HORIZON_WEIGHTS)),
            worst_case_percentile=d.get("worst_case_percentile", DEFAULT_WORST_CASE_PERCENTILE),
            min_valid_results=d.get("min_valid_results", DEFAULT_MIN_VALID_RESULTS),
            max_train_ratio=d.get("max_train_ratio", DEFAULT_MAX_TRAIN_RATIO),
            max_failed_folds=d.get("max_failed_folds", DEFAULT_MAX_FAILED_FOLDS),
            optimization_tier=d.get("optimization_tier", "full"),
            expanding_window=d.get("expanding_window", False),
        )

    @classmethod
    def from_yaml(cls, path: str) -> "RegressionOptimizationConfig":
        """Load config from a YAML file with an `optimization` top-level key."""
        with open(path) as f:
            raw = yaml.safe_load(f)
        section = raw.get("optimization", raw)
        return cls.from_dict(section)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class RegressionTrialResult:
    """Single Optuna trial result with per-fold breakdown."""
    trial_id: int
    params: Dict[str, Any]
    objective_values: Tuple[float, ...]
    benchmark_results: RegressionBenchmarkResults
    passed_gate: bool
    passed_constraint: bool
    fold_results: List[RegressionBenchmarkResults] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "params": self.params,
            "objective_values": list(self.objective_values),
            "benchmark_results": self.benchmark_results.to_dict(),
            "passed_gate": self.passed_gate,
            "passed_constraint": self.passed_constraint,
            "fold_results": [f.to_dict() for f in self.fold_results],
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RegressionTrialResult":
        br = RegressionBenchmarkResults.from_dict(d["benchmark_results"])
        fold_results = [
            RegressionBenchmarkResults.from_dict(fr)
            for fr in d.get("fold_results", [])
        ]
        return cls(
            trial_id=d["trial_id"],
            params=d["params"],
            objective_values=tuple(d["objective_values"]),
            benchmark_results=br,
            passed_gate=d["passed_gate"],
            passed_constraint=d.get("passed_constraint", True),
            fold_results=fold_results,
            timestamp=datetime.fromisoformat(d["timestamp"]),
        )


_RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

@dataclass
class RegressionOptimizationResult:
    """Full result from one MOTPE run, including Pareto front."""
    asset: str
    timeframe: str
    best_params: Dict[str, Any]
    best_objective_values: Tuple[float, ...]
    best_benchmarks: RegressionBenchmarkResults
    pareto_candidates: List[Dict[str, Any]]
    n_trials_passed_gate: int
    n_trials_total: int
    total_time_seconds: float
    config: RegressionOptimizationConfig
    all_trials: List[RegressionTrialResult] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    derived_thresholds: Optional[Dict[str, float]] = None

    def save(self, path: str) -> None:
        import numpy as np

        abs_path = os.path.realpath(path)
        abs_results = os.path.realpath(_RESULTS_DIR)
        if not abs_path.startswith(abs_results + os.sep) and abs_path != abs_results:
            raise ValueError(f"Save path must be under {_RESULTS_DIR}, got {path}")

        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        class _NumpyEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, (np.bool_,)): return bool(obj)
                if isinstance(obj, (np.integer,)): return int(obj)
                if isinstance(obj, (np.floating,)): return float(obj)
                if isinstance(obj, np.ndarray): return obj.tolist()
                return super().default(obj)

        data = {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "best_params": self.best_params,
            "best_objective_values": list(self.best_objective_values),
            "best_benchmarks": self.best_benchmarks.to_dict(),
            "pareto_candidates": self.pareto_candidates,
            "n_trials_passed_gate": self.n_trials_passed_gate,
            "n_trials_total": self.n_trials_total,
            "total_time_seconds": self.total_time_seconds,
            "config": self.config.to_dict(),
            "timestamp": self.timestamp.isoformat(),
            "derived_thresholds": self.derived_thresholds,
            "all_trials": [t.to_dict() for t in self.all_trials],
        }
        with open(abs_path, "w") as f:
            json.dump(data, f, indent=2, cls=_NumpyEncoder)

    @classmethod
    def load(cls, path: str) -> "RegressionOptimizationResult":
        """Load a previously saved optimization result from JSON."""
        with open(path) as f:
            data = json.load(f)

        config = RegressionOptimizationConfig.from_dict(data.get("config", {}))
        best_benchmarks = RegressionBenchmarkResults.from_dict(data["best_benchmarks"])
        all_trials = [
            RegressionTrialResult.from_dict(t) for t in data.get("all_trials", [])
        ]

        return cls(
            asset=data["asset"],
            timeframe=data["timeframe"],
            best_params=data["best_params"],
            best_objective_values=tuple(data["best_objective_values"]),
            best_benchmarks=best_benchmarks,
            pareto_candidates=data.get("pareto_candidates", []),
            n_trials_passed_gate=data["n_trials_passed_gate"],
            n_trials_total=data["n_trials_total"],
            total_time_seconds=data["total_time_seconds"],
            config=config,
            all_trials=all_trials,
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )
