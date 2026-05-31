"""
Data models for regime optimization framework.

All data classes for the 5-parameter optimization of the 4-layer regime pipeline:
  bcpd_hazard_lambda, bcpd_signal_threshold, vol_high_percentile,
  vol_lookback, hmm_retrain_window
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
class BenchmarkResults:
    """Complete benchmark output from a single walk-forward fold evaluation."""

    # Tier 1: Strategy Utility
    sharpe_improvement: float = 0.0      # vs. buy-and-hold
    drawdown_reduction: float = 0.0      # max drawdown improvement

    # Tier 2: Predictive Power
    forward_return_ic: float = 0.0       # Spearman IC vs. 4-bar forward return
    vol_forecast_error: float = 1.0      # lower is better
    ic_decay_score: float = 0.0          # weighted IC across [1, 4, 12, 24] horizons

    # Tier 3: Statistical Validity (GATE)
    levene_p_value: float = 1.0          # must be < validity_p_threshold
    cohens_d: float = 0.0
    passed_validity_gate: bool = False

    # Tier 4: Stability
    avg_regime_duration: float = 0.0     # mean bars per regime episode
    flip_flop_rate: float = 1.0          # fraction of bars with regime change
    transition_entropy: float = 1.0      # entropy of empirical transition matrix

    # Tier 5: Changepoint Quality
    cp_precision: float = 0.0
    detection_lag: float = 999.0
    cp_recall: float = 0.0

    # Meta
    computation_time_ms: float = 0.0
    n_bars: int = 0
    n_regime_changes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sharpe_improvement": self.sharpe_improvement,
            "drawdown_reduction": self.drawdown_reduction,
            "forward_return_ic": self.forward_return_ic,
            "vol_forecast_error": self.vol_forecast_error,
            "ic_decay_score": self.ic_decay_score,
            "levene_p_value": self.levene_p_value,
            "cohens_d": self.cohens_d,
            "passed_validity_gate": self.passed_validity_gate,
            "avg_regime_duration": self.avg_regime_duration,
            "flip_flop_rate": self.flip_flop_rate,
            "transition_entropy": self.transition_entropy,
            "cp_precision": self.cp_precision,
            "detection_lag": self.detection_lag,
            "cp_recall": self.cp_recall,
            "computation_time_ms": self.computation_time_ms,
            "n_bars": self.n_bars,
            "n_regime_changes": self.n_regime_changes,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BenchmarkResults":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Walk-Forward Config
# ---------------------------------------------------------------------------

@dataclass
class WalkForwardConfig:
    """Time-series cross-validation settings."""
    train_bars: int = 4320     # 6 months @ 1h
    test_bars: int = 720       # 1 month @ 1h
    step_bars: int = 720       # roll forward 1 month
    purge_bars: int = 24       # 1-day gap between train/test (default for 1h)
    purge_hours: float = 24.0  # target purge duration in real-world hours
    min_train_bars: int = 2160  # 3 months min

    def purge_bars_for_timeframe(self, timeframe: str) -> int:
        """Compute purge_bars so the gap represents purge_hours regardless of bar size."""
        import math
        from app.regime.orchestrator import timeframe_to_hours
        bar_hours = timeframe_to_hours(timeframe)
        return max(1, math.ceil(self.purge_hours / bar_hours))

    def n_folds(self, total_bars: int) -> int:
        usable = total_bars - self.train_bars - self.purge_bars
        if usable < self.test_bars:
            return 0
        return max(1, (usable - self.test_bars) // self.step_bars + 1)


# ---------------------------------------------------------------------------
# Optimization Weights
# ---------------------------------------------------------------------------

@dataclass
class OptimizationWeights:
    """Tier weights for composite objective. Must sum to 1.0.

    Tier 4 (Stability) is enforced as a hard constraint, NOT optimized —
    rewarding stability lets the optimizer game any parameter that suppresses
    regime transitions (hazard_lambda↑, hmm_retrain_window↑, min_dwell_bars↑).
    Its weight is redistributed to Tier 1 and Tier 2.
    """
    sharpe_improvement: float = 0.325  # Tier 1
    drawdown_reduction: float = 0.175  # Tier 1
    forward_return_ic: float = 0.175   # Tier 2
    vol_forecast_error: float = 0.10   # Tier 2
    ic_decay_score: float = 0.125      # Tier 2
    avg_regime_duration: float = 0.0   # Tier 4 — hard constraint, not weighted
    flip_flop_rate: float = 0.0        # Tier 4 — hard constraint, not weighted
    cp_precision: float = 0.05         # Tier 5
    detection_lag: float = 0.05        # Tier 5

    def validate(self) -> None:
        total = sum([
            self.sharpe_improvement, self.drawdown_reduction,
            self.forward_return_ic, self.vol_forecast_error, self.ic_decay_score,
            self.avg_regime_duration, self.flip_flop_rate,
            self.cp_precision, self.detection_lag,
        ])
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total:.3f}")

    @classmethod
    def classification_only(cls) -> "OptimizationWeights":
        """Tiers 2+5 only (strategy-independent). Sum = 1.0."""
        return cls(
            sharpe_improvement=0.0, drawdown_reduction=0.0,
            forward_return_ic=0.35, vol_forecast_error=0.20,
            ic_decay_score=0.25, cp_precision=0.10, detection_lag=0.10,
        )

    @classmethod
    def balanced(cls) -> "OptimizationWeights":
        """25% strategy, 75% classification. Sum = 1.0."""
        return cls(
            sharpe_improvement=0.1625, drawdown_reduction=0.0875,
            forward_return_ic=0.2625, vol_forecast_error=0.15,
            ic_decay_score=0.1875, cp_precision=0.075, detection_lag=0.075,
        )


# ---------------------------------------------------------------------------
# Optimization Config (search space + run settings)
# ---------------------------------------------------------------------------

@dataclass
class OptimizationConfig:
    """
    Full configuration for one optimization run.

    Search space is defined as (min, max) tuples for each of the 5 params.
    """
    # --- Search space bounds ---
    hazard_lambda: Tuple[float, float] = (50.0, 1000.0)   # cap: 1000 (FX/stocks need longer regimes)
    signal_threshold: Tuple[float, float] = (0.20, 0.60)
    vol_high_percentile: Tuple[float, float] = (65.0, 85.0)  # floor: <65% over-classifies HIGH_VOL
    vol_lookback: Tuple[int, int] = (48, 336)
    hmm_retrain_window: Tuple[int, int] = (300, 2000)
    hurst_lookback: Tuple[int, int] = (50, 200)
    min_dwell_bars: Tuple[int, int] = (3, 25)
    agg_direction_period: Tuple[int, int] = (10, 50)
    agg_bull_roc_thresh: Tuple[float, float] = (0.005, 0.05)
    agg_vol_squeeze_pct: Tuple[float, float] = (10.0, 50.0)
    hilbert_min_period: Tuple[int, int] = (5, 80)
    hilbert_max_period: Tuple[int, int] = (40, 200)

    # Phase 3-4 new optimizable params
    bcpd_hazard_shape: Tuple[float, float] = (0.8, 2.0)       # Weibull: 1.0=constant
    hmm_student_df: Tuple[float, float] = (3.0, 15.0)         # Student-t DoF
    vol_hysteresis_band: Tuple[float, float] = (1.0, 5.0)     # Vol threshold band
    cp_position_decay: Tuple[float, float] = (0.2, 0.8)       # BCPD position decay
    hmm_crisis_vol_mult: Tuple[float, float] = (1.5, 4.0)    # Crisis state vol threshold
    roc_std_window: Tuple[int, int] = (50, 200)               # Adaptive ROC std window

    # --- Run settings ---
    n_trials: int = 100
    timeout_seconds: int = 3600
    n_jobs: int = 1
    sampler: str = "tpe"       # "tpe" | "random" | "cmaes"
    pruner: str = "median"     # "median" | "hyperband" | "none"
    objective_mode: str = "full"  # "full" | "classification" | "balanced"

    # --- Validity gate (Tier 3) ---
    validity_p_threshold: float = 0.05
    soft_gate: bool = True
    validity_penalty: float = 5.0

    # --- Stability constraints (Tier 4 — hard constraints, not optimized) ---
    min_avg_regime_duration: float = 5.0   # bars; penalty if below
    max_flip_flop_rate: float = 0.15       # fraction; penalty if above
    stability_penalty: float = 0.3         # multiplicative penalty on constraint violation

    # --- Walk-forward ---
    walk_forward: WalkForwardConfig = field(default_factory=WalkForwardConfig)

    # --- Weights ---
    weights: OptimizationWeights = field(default_factory=OptimizationWeights)

    @classmethod
    def scalping(cls, **kwargs) -> "OptimizationConfig":
        """
        Search space preset for scalping strategies (1–8 bar holds on 1h bars ≈ 1–8 hours).

        Tight bounds that favour fast regime detection:
        - Short HMM training window → adapts quickly to new micro-regimes
        - Short Hurst lookback → captures near-term trending vs MR character
        - Low hazard_lambda → BCPD fires on small structural breaks
        - Small min_dwell_bars → allows quick label transitions
        - Short Hilbert periods → picks up high-frequency dominant cycles

        Default objective_mode is "classification" — decouple regime quality from
        strategy to avoid overfitting to a specific entry/exit logic.
        """
        base = dict(
            hazard_lambda=(10.0, 150.0),
            signal_threshold=(0.20, 0.60),
            vol_high_percentile=(65.0, 85.0),
            vol_lookback=(24, 168),
            hmm_retrain_window=(100, 600),
            hurst_lookback=(15, 80),
            min_dwell_bars=(2, 8),
            agg_direction_period=(5, 20),
            agg_bull_roc_thresh=(0.005, 0.05),
            agg_vol_squeeze_pct=(10.0, 50.0),
            hilbert_min_period=(5, 25),
            hilbert_max_period=(20, 80),
            bcpd_hazard_shape=(0.8, 2.0),
            hmm_student_df=(3.0, 15.0),
            vol_hysteresis_band=(1.0, 10.0),
            cp_position_decay=(0.2, 0.8),
            hmm_crisis_vol_mult=(1.5, 4.0),
            roc_std_window=(20, 80),
            # Looser stability constraints: scalping accepts faster flipping
            min_avg_regime_duration=3.0,
            max_flip_flop_rate=0.25,
            objective_mode="classification",
        )
        base.update(kwargs)
        return cls(**base)

    @classmethod
    def swing(cls, **kwargs) -> "OptimizationConfig":
        """
        Search space preset for swing strategies (12–80 bar holds on 1h bars ≈ 0.5–3 days).

        Wide bounds that favour stable, durable regime labels:
        - Long HMM training window → stable state estimates over multi-day history
        - Long Hurst lookback → captures persistent trending vs MR across days
        - High hazard_lambda → BCPD only fires on major structural breaks
        - Large min_dwell_bars → regimes must last long enough to hold a swing position
        - Long Hilbert periods → picks up daily/multi-day dominant cycles

        Default objective_mode is "balanced" — 25% strategy weight guides toward
        params that also produce tradeable, low-flip-rate regime sequences.
        """
        base = dict(
            hazard_lambda=(300.0, 3000.0),
            signal_threshold=(0.20, 0.60),
            vol_high_percentile=(65.0, 85.0),
            vol_lookback=(168, 720),
            hmm_retrain_window=(1000, 6000),
            hurst_lookback=(100, 500),
            min_dwell_bars=(12, 80),
            agg_direction_period=(20, 100),
            agg_bull_roc_thresh=(0.01, 0.05),
            agg_vol_squeeze_pct=(10.0, 50.0),
            hilbert_min_period=(20, 100),
            hilbert_max_period=(80, 400),
            bcpd_hazard_shape=(0.8, 2.0),
            hmm_student_df=(3.0, 15.0),
            vol_hysteresis_band=(1.0, 10.0),
            cp_position_decay=(0.2, 0.8),
            hmm_crisis_vol_mult=(1.5, 4.0),
            roc_std_window=(100, 400),
            # Tighter stability constraints: swing cannot tolerate frequent flipping
            min_avg_regime_duration=24.0,
            max_flip_flop_rate=0.06,
            objective_mode="balanced",
        )
        base.update(kwargs)
        return cls(**base)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hazard_lambda": self.hazard_lambda,
            "signal_threshold": self.signal_threshold,
            "vol_high_percentile": self.vol_high_percentile,
            "vol_lookback": self.vol_lookback,
            "hmm_retrain_window": self.hmm_retrain_window,
            "hurst_lookback": self.hurst_lookback,
            "min_dwell_bars": self.min_dwell_bars,
            "agg_direction_period": self.agg_direction_period,
            "agg_bull_roc_thresh": self.agg_bull_roc_thresh,
            "agg_vol_squeeze_pct": self.agg_vol_squeeze_pct,
            "hilbert_min_period": self.hilbert_min_period,
            "hilbert_max_period": self.hilbert_max_period,
            "bcpd_hazard_shape": self.bcpd_hazard_shape,
            "hmm_student_df": self.hmm_student_df,
            "vol_hysteresis_band": self.vol_hysteresis_band,
            "cp_position_decay": self.cp_position_decay,
            "n_trials": self.n_trials,
            "timeout_seconds": self.timeout_seconds,
            "sampler": self.sampler,
            "pruner": self.pruner,
        }


# Alias: SearchSpace was the original name for the search-space portion of
# OptimizationConfig.  Kept for backward compatibility with scripts that
# import ``from app.regime.optimization.models import SearchSpace``.
SearchSpace = OptimizationConfig


# ---------------------------------------------------------------------------
# Trial Result
# ---------------------------------------------------------------------------

@dataclass
class TrialResult:
    """Single Optuna trial result with per-fold breakdown."""
    trial_id: int
    params: Dict[str, Any]
    objective_value: float
    benchmark_results: BenchmarkResults
    passed_gate: bool
    fold_results: List[BenchmarkResults] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "params": self.params,
            "objective_value": self.objective_value,
            "benchmark_results": self.benchmark_results.to_dict(),
            "passed_gate": self.passed_gate,
            "fold_results": [f.to_dict() for f in self.fold_results],
            "timestamp": self.timestamp.isoformat(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# ---------------------------------------------------------------------------
# Optimization Result
# ---------------------------------------------------------------------------

@dataclass
class OptimizationResult:
    """Full result from one optimization run."""
    asset: str
    timeframe: str
    best_params: Dict[str, Any]
    best_objective: float
    best_benchmarks: BenchmarkResults
    n_trials_passed_gate: int
    n_trials_total: int
    total_time_seconds: float
    config: OptimizationConfig
    all_trials: List[TrialResult] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def save(self, path: str) -> None:
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
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: str) -> "OptimizationResult":
        with open(path) as f:
            data = json.load(f)
        best_benchmarks = BenchmarkResults.from_dict(data["best_benchmarks"])
        trials = []
        for t in data.get("all_trials", []):
            br = BenchmarkResults.from_dict(t["benchmark_results"])
            fold_results = [BenchmarkResults.from_dict(fr) for fr in t.get("fold_results", [])]
            trials.append(TrialResult(
                trial_id=t["trial_id"],
                params=t["params"],
                objective_value=t["objective_value"],
                benchmark_results=br,
                passed_gate=t["passed_gate"],
                fold_results=fold_results,
                timestamp=datetime.fromisoformat(t["timestamp"]),
            ))
        cfg_d = data.get("config", {})
        config = OptimizationConfig(
            n_trials=cfg_d.get("n_trials", 100),
            timeout_seconds=cfg_d.get("timeout_seconds", 3600),
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
        """Write best_params into regime.yaml under assets.{asset}.{timeframe}."""
        try:
            import yaml
        except ImportError:
            raise ImportError("PyYAML required: pip install pyyaml")

        with open(yaml_path) as f:
            raw = yaml.safe_load(f) or {}

        raw.setdefault("assets", {})
        raw["assets"].setdefault(self.asset, {})
        raw["assets"][self.asset].setdefault(self.timeframe, {})
        raw["assets"][self.asset][self.timeframe].update({
            "bcpd_hazard_lambda": self.best_params.get("bcpd_hazard_lambda"),
            "bcpd_signal_threshold": self.best_params.get("bcpd_signal_threshold"),
            "vol_high_percentile": self.best_params.get("vol_high_percentile"),
            "vol_lookback": self.best_params.get("vol_lookback"),
            "hmm_retrain_window": self.best_params.get("hmm_retrain_window"),
            "hurst_lookback": self.best_params.get("hurst_lookback"),
            "min_dwell_bars": self.best_params.get("min_dwell_bars"),
            "agg_direction_period": self.best_params.get("agg_direction_period"),
            "agg_bull_roc_thresh": self.best_params.get("agg_bull_roc_thresh"),
            "agg_vol_squeeze_pct": self.best_params.get("agg_vol_squeeze_pct"),
            "hilbert_min_period": self.best_params.get("hilbert_min_period"),
            "hilbert_max_period": self.best_params.get("hilbert_max_period"),
        })
        # Strip None values
        raw["assets"][self.asset][self.timeframe] = {
            k: v for k, v in raw["assets"][self.asset][self.timeframe].items()
            if v is not None
        }

        with open(yaml_path, "w") as f:
            yaml.dump(raw, f, default_flow_style=False, sort_keys=False)
