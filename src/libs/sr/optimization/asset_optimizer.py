"""
Per-Asset S/R Hyperparameter Optimizer (Stage 2)
=================================================
Optimizes per-asset kernel and gate params per (asset, timeframe) using
multi-bar zone quality scoring with walk-forward cross-validation,
trial pruning, gate/constraint penalties, and regularization toward
the Stage 1 global optimum.

Adopted patterns from ``app.regression.optimization``:
  - Rolling walk-forward CV with purge gap (``WalkForwardValidator``)
  - Optuna trial pruning (``MedianPruner``)
  - Zone count gate + survival rate constraint
  - Result persistence (``save`` / ``apply_to_yaml``)
"""

from __future__ import annotations

import copy
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.sr.config_resolver import SRConfigResolver
from app.sr.config_schema import SRResolvedConfig
from app.sr.optimization._shared import (
    DEFAULT_PARAM_VALUES,
    GATE_PARAMS,
    GLOBAL_ONLY_PARAMS,
    RESULTS_DIR,
    OptimizationParameterSpec,
    deep_merge,
    default_parameter_space,
    flat_to_nested,
)
from app.sr.optimization.kernel_screener import (
    KernelScreener,
    KernelSelectionConfig,
    KernelScore,
)
from app.sr.optimization.multi_bar_runner import MultiBarRunResult, MultiBarRunner
from app.sr.optimization.quality_metrics import ZoneQualityEvaluator, ZoneQualityMetrics
from app.sr.pipeline import SRv2Pipeline

logger = logging.getLogger(__name__)

try:
    import optuna

    OPTUNA_AVAILABLE = True
except ImportError:
    optuna = None  # type: ignore[assignment]
    OPTUNA_AVAILABLE = False


# Backward-compatible re-exports (consumed by tests)
_GLOBAL_ONLY_PARAMS = GLOBAL_ONLY_PARAMS
_GATE_PARAMS = GATE_PARAMS
_RESULTS_DIR = RESULTS_DIR


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class AssetOptimizationConfig:
    """Configuration for per-asset Stage 2 optimization."""

    # Optuna
    n_trials: int = 30
    timeout_s: float = 600.0
    sampler: str = "tpe"

    # Search space narrowing
    bound_fraction: float = 0.60  # ±60% of global optimum

    # Walk-forward CV (reuses regression's WalkForwardValidator)
    min_bars: int = 500
    train_bars: int = 2000
    test_bars: int = 500
    step_bars: int = 500
    purge_bars: int = 10

    # Validation rejection
    validation_drop_threshold: float = 0.15

    # Regularization toward global
    regularization_weight: float = 0.05

    # Gate: minimum zone count
    min_zone_count_gate: int = 3
    gate_penalty: float = 0.5

    # Constraint: minimum survival rate
    min_survival_rate_constraint: float = 0.20
    constraint_penalty_floor: float = 0.5

    # Robustness: fold aggregation
    # Percentile for pessimistic fold aggregation (0.10 = 10th pctl).
    # Uses min(mean, p_quantile) when fold count < min_folds_for_pctl
    # to avoid noisy percentiles with very few folds.
    fold_aggregation_pctl: float = 0.10
    min_folds_for_pctl: int = 5
    # CV penalty: score *= (1 - min(cv_penalty_cap, std/(mean+eps)))
    cv_penalty_cap: float = 0.20
    cv_penalty_eps: float = 1e-6

    # Performance: fold stride — evaluate every Nth fold during
    # Optuna trials to reduce wall-clock time.  Adjacent folds overlap
    # heavily (step=100 vs train=300 → 67 % shared bars), so skipping
    # folds loses little signal.  The final train/val evaluation after
    # Optuna always uses ALL folds for accurate scoring.
    fold_stride: int = 3

    # Maximum history passed into the runner at each evaluated bar.
    max_lookback: int = 2000

    # Kernel selection
    kernel_selection_enabled: bool = True

    # Reproducibility
    seed: int = 42

    # Quality evaluator settings
    quality_reversal_threshold_pct: float = 0.015
    quality_coverage_proximity_atr: float = 0.3
    quality_weights: Dict[str, float] = field(default_factory=lambda: {
        "survival_rate": 0.25,
        "touch_accuracy": 0.30,
        "false_breakout_rate": 0.20,
        "strength_stability": 0.10,
        "coverage": 0.15,
    })

    # Scoring mode: "composite" (flat weighted average) or "hierarchical"
    # (hard gates + focused primary = touch_accuracy × (1-FBR)).
    scoring_mode: str = "hierarchical"


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class AssetOptimizationResult:
    """Result from per-asset Stage 2 optimization."""

    asset: str = ""
    timeframe: str = ""
    best_params: Dict[str, float] = field(default_factory=dict)
    train_score: float = 0.0
    val_score: float = 0.0
    accepted: bool = False
    fallback_to_global: bool = False
    n_folds: int = 0
    fold_scores: List[float] = field(default_factory=list)
    gate_failures: int = 0
    constraint_failures: int = 0
    n_trials_total: int = 0
    total_time_seconds: float = 0.0
    selected_kernels: List[str] = field(default_factory=list)
    kernel_scores: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    characteristics_snapshot: Dict[str, float] = field(default_factory=dict)

    def save(self, path: str) -> None:
        """Save result to JSON with path validation."""
        abs_path = os.path.realpath(path)
        abs_results = os.path.realpath(RESULTS_DIR)
        if not abs_path.startswith(abs_results + os.sep) and abs_path != abs_results:
            raise ValueError(
                f"Save path must be under {RESULTS_DIR}, got {path}"
            )

        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        from app.sr.optimization._json_utils import NumpyDatetimeEncoder

        data = {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "best_params": self.best_params,
            "train_score": self.train_score,
            "val_score": self.val_score,
            "accepted": self.accepted,
            "fallback_to_global": self.fallback_to_global,
            "n_folds": self.n_folds,
            "fold_scores": self.fold_scores,
            "gate_failures": self.gate_failures,
            "constraint_failures": self.constraint_failures,
            "n_trials_total": self.n_trials_total,
            "total_time_seconds": self.total_time_seconds,
            "selected_kernels": self.selected_kernels,
            "kernel_scores": self.kernel_scores,
            "timestamp": self.timestamp.isoformat(),
            "characteristics_snapshot": self.characteristics_snapshot,
        }
        with open(abs_path, "w") as f:
            json.dump(data, f, indent=2, cls=NumpyDatetimeEncoder)

    def apply_to_yaml(
        self,
        yaml_path: str,
        backup: bool = True,
    ) -> None:
        """Write best_params into tier-4 per-asset config overrides.

        Params are written into ``assets.<asset>.<timeframe>``
        (Tier 4 per-asset-per-timeframe overrides).
        """
        import shutil

        abs_path = os.path.realpath(yaml_path)
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"YAML config not found: {yaml_path}")

        if backup:
            shutil.copy2(abs_path, abs_path + ".bak")

        try:
            from ruamel.yaml import YAML

            yaml = YAML()
            yaml.preserve_quotes = True
            with open(abs_path) as f:
                cfg = yaml.load(f)

            self._write_params_to_cfg(cfg)

            with open(abs_path, "w") as f:
                yaml.dump(cfg, f)

        except ImportError:
            import yaml as pyyaml

            with open(abs_path) as f:
                cfg = pyyaml.safe_load(f) or {}

            self._write_params_to_cfg(cfg)

            with open(abs_path, "w") as f:
                pyyaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

    def _write_params_to_cfg(self, cfg: dict) -> None:
        """Write per-asset params into config dict structure.

        Uses ``assets.{symbol}.{timeframe}`` layout matching the
        resolver's cascade tier 4.
        """
        if "assets" not in cfg:
            cfg["assets"] = {}
        if self.asset not in cfg["assets"]:
            cfg["assets"][self.asset] = {}
        asset_section = cfg["assets"][self.asset]
        if self.timeframe not in asset_section:
            asset_section[self.timeframe] = {}
        tf_section = asset_section[self.timeframe]

        # Convert flat dotted params to nested config
        from app.sr.optimization._shared import flat_to_nested as _ftn, deep_merge as _dm
        nested_params = _ftn(self.best_params)
        for key, val in nested_params.items():
            if key in tf_section and isinstance(tf_section[key], dict) and isinstance(val, dict):
                tf_section[key] = _dm(tf_section[key], val)
            else:
                tf_section[key] = val

        # Write selected kernels as pipeline.enabled_kernels
        if self.selected_kernels:
            if "pipeline" not in tf_section:
                tf_section["pipeline"] = {}
            tf_section["pipeline"]["enabled_kernels"] = list(self.selected_kernels)

        # Write optimization metadata for staleness tracking
        tf_section["_optimization_meta"] = {
            "last_optimized": self.timestamp.isoformat(),
            "train_score": self.train_score,
            "val_score": self.val_score,
            "n_folds": self.n_folds,
            "characteristics_snapshot": self.characteristics_snapshot,
        }

    @classmethod
    def load(cls, path: str) -> "AssetOptimizationResult":
        """Load result from JSON."""
        with open(path) as f:
            data = json.load(f)
        return cls(
            asset=data["asset"],
            timeframe=data["timeframe"],
            best_params=data["best_params"],
            train_score=data["train_score"],
            val_score=data["val_score"],
            accepted=data["accepted"],
            fallback_to_global=data["fallback_to_global"],
            n_folds=data.get("n_folds", 0),
            fold_scores=data.get("fold_scores", []),
            gate_failures=data.get("gate_failures", 0),
            constraint_failures=data.get("constraint_failures", 0),
            n_trials_total=data.get("n_trials_total", 0),
            total_time_seconds=data.get("total_time_seconds", 0.0),
            selected_kernels=data.get("selected_kernels", []),
            kernel_scores=data.get("kernel_scores", []),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            characteristics_snapshot=data.get("characteristics_snapshot", {}),
        )


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------


class AssetSROptimizer:
    """
    Per-asset S/R optimizer (Stage 2).

    Takes the Stage 1 global optimum as center point, narrows the
    search space to ±bound_fraction, and uses walk-forward CV with
    zone quality scoring to find asset-specific kernel tuning.
    """

    def __init__(
        self,
        asset: str,
        timeframe: str,
        global_best_params: Dict[str, float],
        base_raw_config: Dict[str, Any],
        opt_config: Optional[AssetOptimizationConfig] = None,
    ):
        self._asset = asset
        self._timeframe = timeframe
        self._global_best = global_best_params
        self._base_raw_config = copy.deepcopy(base_raw_config)
        self._config = opt_config or AssetOptimizationConfig()
        self._evaluator = ZoneQualityEvaluator(
            weights=self._config.quality_weights,
            reversal_threshold_pct=self._config.quality_reversal_threshold_pct,
            coverage_proximity_atr=self._config.quality_coverage_proximity_atr,
        )
        self._resolver = SRConfigResolver()

        # Built at optimize() time from actual data
        self._characteristics = None

        # Kernel selection: locked kernel set chosen during optimize()
        self._selected_kernels: List[str] = []
        self._kernel_scores: List[KernelScore] = []

        # Build narrowed per-asset search space from the shared optimizer surface.
        self._param_specs = self._build_narrowed_search_space()

    # ------------------------------------------------------------------
    # Search space
    # ------------------------------------------------------------------

    def _build_narrowed_search_space(
        self,
    ) -> Dict[str, Tuple[float, float, str]]:
        """
        Build narrowed bounds for per-asset params.

                For each non-global optimization parameter:
          low = global_best × (1 - bound_fraction), clamped to original low
          high = global_best × (1 + bound_fraction), clamped to original high

        Gate params (pipeline.min_emit_strength, pipeline.max_new_zones_per_bar)
        narrow around the resolved per-asset YAML value instead of global best.

        Returns dict of {param_name: (low, high, kind)}.
        """
        full_space = default_parameter_space()
        bf = self._config.bound_fraction
        specs: Dict[str, Tuple[float, float, str]] = {}

        # Resolve per-asset config to get gate param defaults
        resolved = self._resolver.resolve(
            self._asset, self._timeframe, self._base_raw_config,
        )

        for name, default_spec in full_space.items():
            # Skip global-only params
            if name in GLOBAL_ONLY_PARAMS:
                continue
            # Skip disabled params
            if not default_spec.enabled:
                continue

            # Gate params use resolved YAML value as center
            if name in GATE_PARAMS:
                center_val = self._resolved_gate_value(name, resolved, default_spec)
            else:
                center_val = self._global_best.get(
                    name, DEFAULT_PARAM_VALUES.get(name, (default_spec.low + default_spec.high) / 2),
                )

            # Narrow bounds around center
            narrowed_low = center_val * (1.0 - bf)
            narrowed_high = center_val * (1.0 + bf)

            # Clamp to original bounds
            clamped_low = max(default_spec.low, narrowed_low)
            clamped_high = min(default_spec.high, narrowed_high)

            # Ensure low < high
            if clamped_low >= clamped_high:
                clamped_low = default_spec.low
                clamped_high = default_spec.high

            specs[name] = (clamped_low, clamped_high, default_spec.kind)

        return specs

    @staticmethod
    def _resolved_gate_value(
        name: str,
        resolved: SRResolvedConfig,
        default_spec: OptimizationParameterSpec,
    ) -> float:
        """Get resolved gate param value from per-asset config."""
        if name == "pipeline.min_emit_strength":
            return resolved.pipeline.min_emit_strength
        if name == "pipeline.max_new_zones_per_bar":
            return float(
                resolved.pipeline.max_new_zones_per_bar
                or DEFAULT_PARAM_VALUES["pipeline.max_new_zones_per_bar"]
            )
        return (default_spec.low + default_spec.high) / 2

    def _apply_data_driven_bounds(self, df: pd.DataFrame) -> None:
        """Narrow ``_param_specs`` in-place using data-derived bounds."""
        from app.sr.optimization.data_driven_bounds import compute_data_driven_bounds

        data_bounds = compute_data_driven_bounds(df)
        if not data_bounds:
            return

        narrowed = 0
        for name, db in data_bounds.items():
            if name not in self._param_specs:
                continue
            old_low, old_high, kind = self._param_specs[name]
            # Intersect data-driven bounds with existing narrowed bounds
            new_low = max(old_low, db.low)
            new_high = min(old_high, db.high)
            if new_low < new_high:
                self._param_specs[name] = (new_low, new_high, kind)
                narrowed += 1
                logger.info(
                    "Data-driven bounds for %s/%s %s: [%.4f, %.4f] → [%.4f, %.4f] (%s)",
                    self._asset, self._timeframe, name,
                    old_low, old_high, new_low, new_high, db.source,
                )

        if narrowed:
            logger.info(
                "Data-driven bounds narrowed %d params for %s/%s",
                narrowed, self._asset, self._timeframe,
            )

    # ------------------------------------------------------------------
    # Walk-forward
    # ------------------------------------------------------------------

    def _build_walk_forward(self) -> "WalkForwardValidator":
        """Build a WalkForwardValidator with SR-specific config."""
        from app.regression.optimization.walk_forward_2way import WalkForwardValidator

        return WalkForwardValidator(
            train_bars=self._config.train_bars,
            test_bars=self._config.test_bars,
            step_bars=self._config.step_bars,
            purge_bars=self._config.purge_bars,
            min_train_bars=self._config.train_bars,
        )

    # ------------------------------------------------------------------
    # Pipeline construction
    # ------------------------------------------------------------------

    def _compute_characteristics(self, df: pd.DataFrame):
        """Build AssetCharacteristics from data for wick-adaptive lifecycle."""
        from app.sr.scripts._utils import build_characteristics

        resolved_base = self._resolver.resolve(
            self._asset, self._timeframe, self._base_raw_config,
        )
        return build_characteristics(
            df, self._asset, self._timeframe,
            metadata=resolved_base.metadata,
        )

    def _build_pipeline(
        self,
        params: Dict[str, float],
    ) -> SRv2Pipeline:
        """Build an SRv2Pipeline with per-asset param overrides merged.

        ``enabled_kernels`` is already locked in ``_base_raw_config``
        by ``_run_kernel_screening``, so no subset selection needed.
        """
        # Convert flat dotted params to nested config overrides
        clean_params = {k: v for k, v in params.items() if not k.startswith("_")}
        overrides = flat_to_nested(clean_params)

        # Merge overrides into base config's sr section
        raw_config = copy.deepcopy(self._base_raw_config)
        sr_section = raw_config.get("sr", {})
        raw_config["sr"] = deep_merge(sr_section, overrides)

        # Also inject global-only params from Stage 1
        for gname in GLOBAL_ONLY_PARAMS:
            if gname in self._global_best:
                parts = gname.split(".")
                cursor = raw_config["sr"]
                for part in parts[:-1]:
                    cursor = cursor.setdefault(part, {})
                cursor[parts[-1]] = self._global_best[gname]

        resolved = self._resolver.resolve(
            self._asset, self._timeframe, raw_config,
            characteristics=self._characteristics,
        )
        return SRv2Pipeline(resolved, asset=self._asset, timeframe=self._timeframe)

    # ------------------------------------------------------------------
    # Fold evaluation
    # ------------------------------------------------------------------

    def _evaluate_fold(
        self,
        params: Dict[str, float],
        df: pd.DataFrame,
        start_bar: int = 0,
        end_bar: Optional[int] = None,
        score_start_bar: Optional[int] = None,
    ) -> Tuple[float, ZoneQualityMetrics, int, int]:
        """
        Evaluate params over a bar window with full-history warmup.

        Returns (score, metrics, gate_failed, constraint_failed).
        gate_failed / constraint_failed are 0 or 1 for counting.
        """
        pipeline = self._build_pipeline(params)
        runner = MultiBarRunner(pipeline)
        run_result = runner.run(
            df,
            start_bar=start_bar,
            end_bar=end_bar,
            max_lookback=self._config.max_lookback,
        )

        score_result = self._slice_run_result_for_scoring(
            run_result,
            start_bar=start_bar,
            score_start_bar=score_start_bar,
        )

        metrics = self._evaluator.evaluate(score_result)
        if self._config.scoring_mode == "hierarchical":
            raw_score = self._evaluator.hierarchical_score(metrics)
        else:
            raw_score = self._evaluator.composite_score(metrics)

        # Gate: zone count
        gate_mult = 1.0
        gate_failed = 0
        if run_result.total_zones_created < self._config.min_zone_count_gate:
            gate_mult = self._config.gate_penalty
            gate_failed = 1

        # Constraint: survival rate
        # Skip in hierarchical mode — hierarchical_score() already gates
        # on min_survival internally; applying this again double-penalizes.
        constraint_mult = 1.0
        constraint_failed = 0
        if self._config.scoring_mode != "hierarchical":
            min_surv = self._config.min_survival_rate_constraint
            if min_surv > 0 and metrics.survival_rate < min_surv:
                floor = self._config.constraint_penalty_floor
                constraint_mult = floor + (1.0 - floor) * (metrics.survival_rate / min_surv)
                constraint_failed = 1

        # Regularization penalty
        reg_penalty = self._regularization_penalty(params)

        score = raw_score * gate_mult * constraint_mult - reg_penalty
        return score, metrics, gate_failed, constraint_failed

    @staticmethod
    def _slice_run_result_for_scoring(
        run_result: MultiBarRunResult,
        start_bar: int,
        score_start_bar: Optional[int],
    ) -> MultiBarRunResult:
        """Restrict score-sensitive slices to a later bar without resetting state."""
        if score_start_bar is None or score_start_bar <= start_bar:
            return run_result

        filtered_events = [
            event for event in run_result.all_events
            if event.bar_index >= score_start_bar
        ]

        first_snapshot_bar = start_bar if start_bar > 0 else 1
        offset = max(0, score_start_bar - first_snapshot_bar)

        return MultiBarRunResult(
            bar_count=max(0, run_result.bar_count - max(0, score_start_bar - start_bar)),
            all_events=filtered_events,
            final_zones=list(run_result.final_zones),
            total_zones_created=run_result.total_zones_created,
            total_touches=sum(
                1 for event in filtered_events
                if event.trigger in ("touch", "touch_confirm")
            ),
            total_breakouts=sum(
                1 for event in filtered_events
                if event.trigger.startswith("breakout_")
            ),
            total_false_breakouts=sum(
                1 for event in filtered_events
                if event.trigger == "price_returned"
            ),
            zones_reached_active=run_result.zones_reached_active,
            zones_broken=run_result.zones_broken,
            zones_expired=run_result.zones_expired,
            close_prices=run_result.close_prices[offset:],
            bar_zone_snapshots=run_result.bar_zone_snapshots[offset:],
        )

    def _regularization_penalty(self, params: Dict[str, float]) -> float:
        """Penalize deviation from global optimum."""
        if self._config.regularization_weight <= 0:
            return 0.0

        deviations: List[float] = []
        for name, (low, high, _kind) in self._param_specs.items():
            if name not in params:
                continue
            global_val = self._global_best.get(name, (low + high) / 2)
            bound_range = high - low
            if bound_range <= 0:
                continue
            deviations.append(abs(params[name] - global_val) / bound_range)

        if not deviations:
            return 0.0
        return self._config.regularization_weight * (sum(deviations) / len(deviations))

    # ------------------------------------------------------------------
    # Optuna interface
    # ------------------------------------------------------------------

    def _suggest_params(self, trial: "optuna.Trial") -> Dict[str, float]:
        """Suggest params from the narrowed search space.

        Kernel selection is decoupled: ``_run_kernel_screening`` locks
        the kernel set before Optuna starts, so there is no
        ``kernel_subset_idx`` categorical here.
        """
        params: Dict[str, float] = {}
        for name, (low, high, kind) in self._param_specs.items():
            if kind == "int":
                params[name] = trial.suggest_int(name, int(low), int(high))
            else:
                params[name] = trial.suggest_float(name, low, high)
        return params

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(
        self,
        df: pd.DataFrame,
        callbacks: Optional[List] = None,
    ) -> AssetOptimizationResult:
        """
        Run per-asset optimization with walk-forward CV.

        Before starting trials, narrows bounds further using
        data-driven statistics from *df*.

        If Optuna is not available, falls back to evaluating global
        defaults and returning them as-is.

        Args:
            df: OHLCV DataFrame.
            callbacks: Optional Optuna callbacks ``(study, trial) -> None``.
        """
        # Narrow search space with per-asset data distributions
        self._apply_data_driven_bounds(df)

        # Build AssetCharacteristics from data for wick-adaptive lifecycle
        self._characteristics = self._compute_characteristics(df)

        # Run kernel screening to build per-asset kernel subsets
        if self._config.kernel_selection_enabled:
            self._run_kernel_screening(df)

        if len(df) < self._config.min_bars:
            logger.warning(
                "Insufficient data for %s/%s: %d bars < %d min_bars",
                self._asset, self._timeframe, len(df), self._config.min_bars,
            )
            return self._fallback_result("insufficient_data")

        if not OPTUNA_AVAILABLE:
            logger.warning(
                "Optuna not available — evaluating %s/%s with global defaults",
                self._asset, self._timeframe,
            )
            return self._evaluate_defaults(df)

        return self._run_optuna(df, callbacks=callbacks)

    def _run_kernel_screening(self, df: pd.DataFrame) -> None:
        """Screen kernels, pick the best set, and lock it.

        Instead of handing Optuna a categorical over N subsets,
        we deterministically pick all passing kernels (the largest
        viable subset) and lock them as ``enabled_kernels``.
        Optuna then only tunes the continuous params for those
        kernels, dramatically reducing dimensionality.
        """
        ks_raw = (
            self._base_raw_config
            .get("sr", {})
            .get("optimization", {})
            .get("kernel_selection", {})
        )
        ks_config = KernelSelectionConfig.from_yaml(ks_raw)

        screener = KernelScreener(
            asset=self._asset,
            timeframe=self._timeframe,
            base_raw_config=self._base_raw_config,
            config=ks_config,
            characteristics=self._characteristics,
        )

        scores = screener.screen(df, max_lookback=self._config.max_lookback)
        self._kernel_scores = scores

        # Pick all passing kernels as the locked set
        passed = [s.kernel for s in scores if s.passed]
        if not passed:
            # Fall back to anchor kernels
            passed = list(ks_config.anchor_kernels)
            logger.warning(
                "%s/%s: no kernels passed screening — "
                "falling back to anchors: %s",
                self._asset, self._timeframe, passed,
            )

        self._selected_kernels = passed

        # Lock enabled_kernels in base_raw_config so _build_pipeline
        # always uses this set (no Optuna categorical needed).
        sr = self._base_raw_config.setdefault("sr", {})
        sr.setdefault("pipeline", {})["enabled_kernels"] = list(passed)

        # Also override any per-asset/TF enabled_kernels that could
        # shadow the global setting via the resolver cascade.
        assets = self._base_raw_config.setdefault("assets", {})
        asset_cfg = assets.setdefault(self._asset, {})
        tf_cfg = asset_cfg.setdefault(self._timeframe, {})
        tf_cfg.setdefault("pipeline", {})["enabled_kernels"] = list(passed)
        defaults_cfg = asset_cfg.get("defaults", {})
        if defaults_cfg and "pipeline" in defaults_cfg:
            defaults_cfg["pipeline"]["enabled_kernels"] = list(passed)

        # Drop kernel params for kernels NOT in the locked set
        # so Optuna doesn't waste dimensions on them.
        to_drop = [
            name for name in self._param_specs
            if name.startswith("kernels.")
            and name.split(".")[1] not in passed
        ]
        for name in to_drop:
            del self._param_specs[name]

        logger.info(
            "%s/%s kernel screening: %d/%d passed → locked %s "
            "(dropped %d unused kernel params, %d params remain)",
            self._asset, self._timeframe,
            len(passed), len(scores), passed,
            len(to_drop), len(self._param_specs),
        )

    def _run_optuna(
        self,
        df: pd.DataFrame,
        callbacks: Optional[List] = None,
    ) -> AssetOptimizationResult:
        """Run the full Optuna optimization loop."""
        wf = self._build_walk_forward()
        splits = wf.get_splits(len(df))

        if not splits:
            logger.warning(
                "No walk-forward splits possible for %s/%s (%d bars)",
                self._asset, self._timeframe, len(df),
            )
            return self._evaluate_defaults(df)

        start_time = time.time()

        # Pre-compute strided split indices for fast trial evaluation.
        # Adjacent folds overlap heavily, so evaluating every Nth fold
        # during Optuna trials is a safe approximation.  The final
        # train/val scoring after Optuna always uses ALL folds.
        stride = max(1, self._config.fold_stride)
        all_split_list = splits
        strided_splits = all_split_list[::stride]
        n_full = len(all_split_list)
        n_strided = len(strided_splits)
        if stride > 1 and n_strided < n_full:
            logger.info(
                "Fold stride=%d: using %d/%d folds per trial (%.0f%% reduction)",
                stride, n_strided, n_full,
                (1 - n_strided / n_full) * 100,
            )

        # Track gate/constraint failures across all trials
        total_gate_failures = 0
        total_constraint_failures = 0
        all_fold_scores: List[List[float]] = []

        def objective(trial: "optuna.Trial") -> float:
            nonlocal total_gate_failures, total_constraint_failures
            params = self._suggest_params(trial)
            fold_scores: List[float] = []
            # Per-metric fold tracking for dispersion logging
            fold_metrics: Dict[str, List[float]] = {
                "survival_rate": [], "touch_accuracy": [],
                "false_breakout_rate": [], "strength_stability": [],
                "coverage": [],
            }

            for fold_idx, split in enumerate(strided_splits):
                score, metrics, gf, cf = self._evaluate_fold(
                    params,
                    df,
                    start_bar=split.train_start,
                    end_bar=split.test_end - 1,
                    score_start_bar=split.test_start,
                )
                fold_scores.append(score)
                fold_metrics["survival_rate"].append(metrics.survival_rate)
                fold_metrics["touch_accuracy"].append(metrics.touch_accuracy)
                fold_metrics["false_breakout_rate"].append(metrics.false_breakout_rate)
                fold_metrics["strength_stability"].append(metrics.strength_stability)
                fold_metrics["coverage"].append(metrics.coverage)
                total_gate_failures += gf
                total_constraint_failures += cf

                # Report intermediate for pruning
                running_mean = float(np.mean(fold_scores))
                trial.report(running_mean, fold_idx)
                if trial.should_prune():
                    raise optuna.TrialPruned()

            all_fold_scores.append(fold_scores)

            # --- Pessimistic fold aggregation ---
            arr = np.array(fold_scores)
            mu = float(np.mean(arr))
            cfg = self._config
            if len(arr) >= cfg.min_folds_for_pctl:
                base = float(np.percentile(arr, cfg.fold_aggregation_pctl * 100))
            else:
                # Too few folds for reliable percentile — use min(mean, p25)
                base = min(mu, float(np.percentile(arr, 25)))

            # --- CV penalty ---
            sigma = float(np.std(arr))
            cv = sigma / (mu + cfg.cv_penalty_eps)
            cv_pen = min(cfg.cv_penalty_cap, cv)
            score = base * (1.0 - cv_pen)

            # --- Log per-metric fold dispersion as trial attributes ---
            for metric_name, values in fold_metrics.items():
                m_arr = np.array(values)
                trial.set_user_attr(f"fold_{metric_name}_mean", float(np.mean(m_arr)))
                trial.set_user_attr(f"fold_{metric_name}_std", float(np.std(m_arr)))
            trial.set_user_attr("fold_composite_mean", mu)
            trial.set_user_attr("fold_composite_p10", float(np.percentile(arr, 10)))
            trial.set_user_attr("fold_composite_cv", cv)
            trial.set_user_attr("cv_penalty_applied", cv_pen)

            return score

        sampler = self._create_sampler()
        pruner = optuna.pruners.MedianPruner(
            n_startup_trials=3, n_warmup_steps=1,
        )
        study = optuna.create_study(
            direction="maximize", sampler=sampler, pruner=pruner,
        )

        # Warm-start: seed with global per-asset params so Optuna
        # starts from a known-good point rather than pure random.
        seed_params = self._global_per_asset_params()
        # Only enqueue params that exist in the search space
        enqueue_params = {
            name: seed_params[name]
            for name in self._param_specs
            if name in seed_params
        }
        if enqueue_params:
            study.enqueue_trial(enqueue_params)

        study.optimize(
            objective,
            n_trials=self._config.n_trials,
            timeout=self._config.timeout_s,
            callbacks=callbacks or [],
        )

        total_time = time.time() - start_time
        best_params = dict(study.best_params)

        # --- Coverage diagnostics: top-N trial analysis ---
        self._log_coverage_diagnostics(study)

        # Kernel set was locked before Optuna started
        selected_kernels = list(self._selected_kernels)

        # Validate: re-evaluate best on train vs validation folds
        train_scores, val_scores = self._train_val_scores(best_params, df, wf)
        mean_train = float(np.mean(train_scores)) if train_scores else 0.0
        mean_val = float(np.mean(val_scores)) if val_scores else 0.0

        # Rejection check
        threshold = 1.0 - self._config.validation_drop_threshold
        accepted = mean_val >= mean_train * threshold

        if not accepted:
            logger.info(
                "%s/%s: validation rejected (train=%.4f, val=%.4f, threshold=%.2f)",
                self._asset, self._timeframe, mean_train, mean_val, threshold,
            )
            best_params = self._global_per_asset_params()

        return AssetOptimizationResult(
            asset=self._asset,
            timeframe=self._timeframe,
            best_params=best_params,
            train_score=mean_train,
            val_score=mean_val,
            accepted=accepted,
            fallback_to_global=not accepted,
            n_folds=len(splits),
            fold_scores=all_fold_scores[-1] if all_fold_scores else [],
            gate_failures=total_gate_failures,
            constraint_failures=total_constraint_failures,
            n_trials_total=len(study.trials),
            total_time_seconds=total_time,
            selected_kernels=selected_kernels,
            kernel_scores=[
                {
                    "kernel": s.kernel,
                    "composite": s.composite,
                    "survival_rate": s.survival_rate,
                    "touch_accuracy": s.touch_accuracy,
                    "zones_created": s.zones_created,
                    "passed": s.passed,
                }
                for s in self._kernel_scores
            ],
            characteristics_snapshot=self._characteristics_snapshot(),
        )

    def _log_coverage_diagnostics(self, study: "optuna.Study") -> None:
        """Log coverage behavior across top trials for diagnostic insight.

        Analyses completed trials to surface:
        - Coverage distribution of top-N trials vs all trials
        - Per-metric fold dispersion comparison (coverage vs touch/survival)
        - Whether low-coverage winners look artificially good on other metrics
        """
        completed = [
            t for t in study.trials
            if t.state == optuna.trial.TrialState.COMPLETE
        ]
        if len(completed) < 3:
            return

        # Sort by objective value (descending — maximize)
        completed.sort(key=lambda t: t.value, reverse=True)
        top_n = min(5, len(completed))
        top_trials = completed[:top_n]

        # Extract coverage stats from trial user_attrs
        def _attr(t: "optuna.Trial", key: str, default: float = 0.0) -> float:
            return t.user_attrs.get(key, default)

        top_cov_means = [_attr(t, "fold_coverage_mean") for t in top_trials]
        all_cov_means = [_attr(t, "fold_coverage_mean") for t in completed]

        top_cov_stds = [_attr(t, "fold_coverage_std") for t in top_trials]
        top_surv_stds = [_attr(t, "fold_survival_rate_std") for t in top_trials]
        top_touch_stds = [_attr(t, "fold_touch_accuracy_std") for t in top_trials]

        top_cov_arr = np.array(top_cov_means) if top_cov_means else np.array([0.0])
        all_cov_arr = np.array(all_cov_means) if all_cov_means else np.array([0.0])

        logger.info(
            "%s/%s coverage diagnostics (top-%d of %d trials): "
            "top_cov=[%.4f ± %.4f], all_cov=[%.4f ± %.4f], "
            "top_cov_fold_std=%.4f, top_surv_fold_std=%.4f, top_touch_fold_std=%.4f",
            self._asset, self._timeframe, top_n, len(completed),
            float(np.mean(top_cov_arr)), float(np.std(top_cov_arr)),
            float(np.mean(all_cov_arr)), float(np.std(all_cov_arr)),
            float(np.mean(top_cov_stds)) if top_cov_stds else 0.0,
            float(np.mean(top_surv_stds)) if top_surv_stds else 0.0,
            float(np.mean(top_touch_stds)) if top_touch_stds else 0.0,
        )

        # Flag if best trial has coverage well below population median
        best = completed[0]
        median_cov = float(np.median(all_cov_arr))
        best_cov = _attr(best, "fold_coverage_mean")
        if median_cov > 0 and best_cov < median_cov * 0.5:
            logger.warning(
                "%s/%s coverage anomaly: best trial coverage=%.4f is <50%% of "
                "population median=%.4f — may indicate artificially inflated "
                "composite from sparse-but-high-quality zones",
                self._asset, self._timeframe, best_cov, median_cov,
            )

    def _train_val_scores(
        self,
        params: Dict[str, float],
        df: pd.DataFrame,
        wf: "WalkForwardValidator",
    ) -> Tuple[List[float], List[float]]:
        """Evaluate best params on train and validation splits separately.

        Uses the same fold stride as Optuna trials to keep runtime
        proportional.
        """
        train_scores: List[float] = []
        val_scores: List[float] = []

        stride = max(1, self._config.fold_stride)
        all_splits = wf.get_splits(len(df))
        strided = all_splits[::stride]

        for split in strided:
            train_score, _, _, _ = self._evaluate_fold(
                params,
                df,
                start_bar=split.train_start,
                end_bar=split.train_end - 1,
            )
            val_score, _, _, _ = self._evaluate_fold(
                params,
                df,
                start_bar=split.train_start,
                end_bar=split.test_end - 1,
                score_start_bar=split.test_start,
            )
            train_scores.append(train_score)
            val_scores.append(val_score)

        return train_scores, val_scores

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def _evaluate_defaults(self, df: pd.DataFrame) -> AssetOptimizationResult:
        """Evaluate global defaults across walk-forward folds."""
        params = self._global_per_asset_params()
        wf = self._build_walk_forward()
        fold_scores: List[float] = []

        for split in wf.get_splits(len(df)):
            score, _, _, _ = self._evaluate_fold(
                params,
                df,
                start_bar=split.train_start,
                end_bar=split.train_end - 1,
            )
            fold_scores.append(score)

        return AssetOptimizationResult(
            asset=self._asset,
            timeframe=self._timeframe,
            best_params=params,
            train_score=float(np.mean(fold_scores)) if fold_scores else 0.0,
            val_score=0.0,
            accepted=True,
            fallback_to_global=True,
            n_folds=len(fold_scores),
            fold_scores=fold_scores,
            characteristics_snapshot=self._characteristics_snapshot(),
        )

    def _fallback_result(self, reason: str) -> AssetOptimizationResult:
        """Return a result with global defaults without evaluation."""
        return AssetOptimizationResult(
            asset=self._asset,
            timeframe=self._timeframe,
            best_params=self._global_per_asset_params(),
            accepted=False,
            fallback_to_global=True,
            characteristics_snapshot=self._characteristics_snapshot(),
        )

    def _global_per_asset_params(self) -> Dict[str, float]:
        """Extract only the per-asset params from global best."""
        return {
            name: self._global_best.get(name, DEFAULT_PARAM_VALUES.get(name, 0.0))
            for name in self._param_specs
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _characteristics_snapshot(self) -> Dict[str, float]:
        """Extract key numeric fields from AssetCharacteristics for staleness tracking."""
        if self._characteristics is None:
            return {}
        c = self._characteristics
        return {
            "atr": c.atr,
            "atr_pct": c.atr_pct,
            "hurst": c.hurst,
            "wick_body_ratio": c.wick_body_ratio,
            "wick_p75_atr": c.wick_p75_atr,
            "body_p50_atr": c.body_p50_atr,
            "range_p90_atr": c.range_p90_atr,
        }

    def _create_sampler(self) -> "optuna.samplers.BaseSampler":
        """Create Optuna sampler from config."""
        s = self._config.sampler.lower()
        seed = self._config.seed
        if s == "cmaes":
            return optuna.samplers.CmaEsSampler(seed=seed)
        if s == "random":
            return optuna.samplers.RandomSampler(seed=seed)
        return optuna.samplers.TPESampler(seed=seed)

    @property
    def param_specs(self) -> Dict[str, Tuple[float, float, str]]:
        """Expose narrowed search space for testing."""
        return dict(self._param_specs)
