"""
Universe-Wide S/R Optimizer
=============================
Universe-scale joint optimization for the approved shared SR parameter surface.

All optimization parameters use canonical dotted identities so the trial
surface matches the live SR config contract exactly.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.sr.config_schema import OptimizationConfig, OptimizationParameterConfig
from app.sr.config_resolver import SRConfigResolver
from app.sr.cross_asset import CrossAssetConfig, CrossAssetSRAnalyzer
from app.sr.optimization._shared import (
    DEFAULT_PARAM_VALUES,
    STAGE2_ONLY_PARAMS,
    OptimizationParameterSpec,
    deep_merge,
    default_parameter_space,
    flat_to_nested,
)
from app.sr.optimization.benchmark_tier6 import CrossAssetBenchmark, CrossAssetBenchmarkResult
from app.sr.universe.config import UniverseSRConfig
from app.sr.universe.router import UniverseSRRouter

logger = logging.getLogger(__name__)

try:
    import optuna
    OPTUNA_AVAILABLE = True
except ImportError:
    optuna = None  # type: ignore
    OPTUNA_AVAILABLE = False


# ---------------------------------------------------------------------------
# Backward-compatible re-exports (consumed by asset_optimizer, tests, scripts)
# ---------------------------------------------------------------------------

_default_parameter_space = default_parameter_space
_DEFAULT_PARAM_VALUES = DEFAULT_PARAM_VALUES
_deep_merge = deep_merge
_STAGE2_ONLY_PARAMS = STAGE2_ONLY_PARAMS



# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UniverseOptimizationConfig:
    """Configuration for universe-wide optimization."""

    # Optuna
    n_trials: int = 50
    timeout_s: float = 3600.0

    # Lightweight objective weighting
    tier6_weight: float = 0.100

    # Trailing bars to score per asset during Stage 1 trials.
    stage1_eval_bars: int = 300

    # Canonical search space keyed by dotted runtime identities.
    parameter_space: Dict[str, OptimizationParameterSpec] = field(
        default_factory=_default_parameter_space,
    )

    # Reproducibility
    seed: int = 42

    @classmethod
    def from_resolved_config(
        cls,
        config: Optional[OptimizationConfig],
    ) -> "UniverseOptimizationConfig":
        if config is None:
            return cls()

        default_space = _default_parameter_space()
        parameter_space: Dict[str, OptimizationParameterSpec] = {}
        for name, default_spec in default_space.items():
            resolved_spec = config.parameters.get(name)
            if resolved_spec is None:
                parameter_space[name] = default_spec
                continue
            parameter_space[name] = OptimizationParameterSpec(
                low=default_spec.low if resolved_spec.low is None else resolved_spec.low,
                high=default_spec.high if resolved_spec.high is None else resolved_spec.high,
                kind=resolved_spec.kind,
                enabled=resolved_spec.enabled,
                metadata_gate=resolved_spec.metadata_gate,
            )

        return cls(
            n_trials=config.n_trials,
            timeout_s=config.timeout_s,
            tier6_weight=config.tier6_weight,
            stage1_eval_bars=config.stage1_eval_bars,
            parameter_space=parameter_space,
        )

    @classmethod
    def from_dict(cls, config_dict: Optional[Dict[str, Any]]) -> "UniverseOptimizationConfig":
        if not config_dict:
            return cls()

        default_space = _default_parameter_space()
        raw_parameters = config_dict.get("parameters", {})
        parameter_space: Dict[str, OptimizationParameterSpec] = {}
        for name, default_spec in default_space.items():
            raw_spec = raw_parameters.get(name, {})
            if not isinstance(raw_spec, dict):
                raw_spec = {}
            parameter_space[name] = OptimizationParameterSpec(
                low=raw_spec.get("low", default_spec.low),
                high=raw_spec.get("high", default_spec.high),
                kind=raw_spec.get("kind", default_spec.kind),
                enabled=raw_spec.get("enabled", default_spec.enabled),
                metadata_gate=raw_spec.get("metadata_gate", default_spec.metadata_gate),
            )

        return cls(
            n_trials=int(config_dict.get("n_trials", cls.n_trials)),
            timeout_s=float(config_dict.get("timeout_s", cls.timeout_s)),
            tier6_weight=float(config_dict.get("tier6_weight", cls.tier6_weight)),
            stage1_eval_bars=int(config_dict.get("stage1_eval_bars", cls.stage1_eval_bars)),
            parameter_space=parameter_space,
        )


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class UniverseTrialResult:
    """Result from a single optimization trial."""
    trial_number: int
    params: Dict[str, float]
    per_asset_scores: Dict[str, float] = field(default_factory=dict)
    cross_asset_score: float = 0.0
    total_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UniverseOptimizationResult:
    """Full optimization output."""
    best_params: Dict[str, float] = field(default_factory=dict)
    best_score: float = 0.0
    all_trials: List[UniverseTrialResult] = field(default_factory=list)
    tier6_result: Optional[CrossAssetBenchmarkResult] = None
    assets: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------

class UniverseSROptimizer:
    """
    Universe-wide joint optimizer for S/R parameters.

    Uses the v2 ``UniverseSRRouter`` to run per-asset pipelines,
    then applies ``CrossAssetSRAnalyzer`` + Tier 6 benchmark.
    """

    def __init__(
        self,
        universe_config: UniverseSRConfig,
        opt_config: Optional[UniverseOptimizationConfig] = None,
    ):
        self._universe_config = universe_config
        self._resolver = SRConfigResolver()
        self._opt_config = opt_config or UniverseOptimizationConfig.from_resolved_config(
            self._resolver.resolve_typed_optimization_config(self._build_raw_resolver_config()),
        )
        self._tier6 = CrossAssetBenchmark()

    def _build_raw_resolver_config(self) -> Dict[str, Any]:
        """Normalize universe-global config into resolver-shaped raw config."""
        raw_global = copy.deepcopy(self._universe_config.global_config)
        raw_config: Dict[str, Any] = {
            "asset_metadata": copy.deepcopy(raw_global.get("asset_metadata", {})),
            "sr": copy.deepcopy(raw_global.get("sr", {})),
            "per_tf": copy.deepcopy(raw_global.get("per_tf", {})),
            "assets": copy.deepcopy(raw_global.get("assets", {})),
        }

        top_level_global = {
            key: value
            for key, value in raw_global.items()
            if key not in {"asset_metadata", "sr", "per_tf", "assets"}
        }
        if top_level_global:
            raw_config["sr"] = deep_merge(raw_config["sr"], top_level_global)
        return raw_config

    def _configured_timeframe(self, symbol: str) -> str:
        asset_config = next(
            (asset for asset in self._universe_config.assets if asset.symbol == symbol),
            None,
        )
        if asset_config and asset_config.timeframes:
            return asset_config.timeframes[0]
        if self._universe_config.default_timeframes:
            return self._universe_config.default_timeframes[0]
        logger.warning(
            "No timeframe configured for %s — falling back to '1h'", symbol,
        )
        return "1h"

    def _universe_has_session_gaps(self) -> bool:
        raw_config = self._build_raw_resolver_config()
        for asset in self._universe_config.assets:
            resolved = self._resolver.resolve(
                symbol=asset.symbol,
                timeframe=self._configured_timeframe(asset.symbol),
                raw_config=raw_config,
            )
            if resolved.metadata.has_session_gaps:
                return True
        return False

    def _enabled_parameter_space(self) -> Dict[str, OptimizationParameterSpec]:
        session_gap_allowed = self._universe_has_session_gaps()
        enabled: Dict[str, OptimizationParameterSpec] = {}
        for name, spec in self._opt_config.parameter_space.items():
            if name in STAGE2_ONLY_PARAMS:
                continue
            if not spec.enabled:
                continue
            if spec.metadata_gate == "has_session_gaps" and not session_gap_allowed:
                continue
            enabled[name] = spec
        return enabled

    def _current_global_sr_config(self) -> Dict[str, Any]:
        return self._build_raw_resolver_config().get("sr", {})

    def _current_value(self, param_name: str) -> Any:
        current: Any = self._current_global_sr_config()
        for part in param_name.split("."):
            if not isinstance(current, dict) or part not in current:
                return DEFAULT_PARAM_VALUES[param_name]
            current = current[part]
        return current

    def _default_params(self) -> Dict[str, float]:
        defaults: Dict[str, float] = {}
        for name, spec in self._enabled_parameter_space().items():
            value = self._current_value(name)
            defaults[name] = int(value) if spec.kind == "int" else float(value)
        return defaults

    def _flatten_scored_levels(
        self,
        universe_result: "UniverseResult",
    ) -> Dict[str, List[Any]]:
        flattened: Dict[str, List[Any]] = {}
        for asset, tf_results in universe_result.results.items():
            flattened[asset] = []
            for asset_timeframe_result in tf_results.values():
                flattened[asset].extend(asset_timeframe_result.result.scored_levels)
        return flattened

    def _build_cross_asset_analyzer(
        self,
        params: Optional[Dict[str, float]] = None,
    ) -> CrossAssetSRAnalyzer:
        """Build a cross-asset analyzer from trial parameters."""
        defaults = CrossAssetConfig()
        current = self._current_global_sr_config().get("cross_asset", {})
        sector_cluster_eps_atr = current.get(
            "sector_cluster_eps_atr", defaults.sector_cluster_eps_atr,
        )
        if params is not None:
            sector_cluster_eps_atr = params.get(
                "cross_asset.sector_cluster_eps_atr",
                sector_cluster_eps_atr,
            )
        return CrossAssetSRAnalyzer(
            CrossAssetConfig(
                correlation_threshold=current.get(
                    "correlation_threshold", defaults.correlation_threshold,
                ),
                min_universe_agreement=current.get(
                    "min_universe_agreement", defaults.min_universe_agreement,
                ),
                sector_cluster_eps_atr=sector_cluster_eps_atr,
                agreement_strength_bonus=current.get(
                    "agreement_strength_bonus", defaults.agreement_strength_bonus,
                ),
                max_comparison_assets=current.get(
                    "max_comparison_assets", defaults.max_comparison_assets,
                ),
            ),
        )

    def _apply_data_driven_bounds(
        self, data_map: Dict[str, Dict[str, pd.DataFrame]]
    ) -> None:
        """Narrow ``parameter_space`` in-place using data-derived bounds."""
        from app.sr.optimization.data_driven_bounds import (
            compute_data_driven_bounds,
            narrow_parameter_space,
        )

        # Concatenate all DataFrames for a universe-wide distribution
        frames = [df for tf_map in data_map.values() for df in tf_map.values()]
        if not frames:
            return
        combined = pd.concat(frames, ignore_index=True)
        data_bounds = compute_data_driven_bounds(combined)
        if not data_bounds:
            return

        self._opt_config = UniverseOptimizationConfig(
            n_trials=self._opt_config.n_trials,
            timeout_s=self._opt_config.timeout_s,
            tier6_weight=self._opt_config.tier6_weight,
            stage1_eval_bars=self._opt_config.stage1_eval_bars,
            parameter_space=narrow_parameter_space(
                self._opt_config.parameter_space, data_bounds,
            ),
            seed=self._opt_config.seed,
        )
        logger.info(
            "Data-driven bounds narrowed %d of %d params",
            len(data_bounds),
            len(self._opt_config.parameter_space),
        )

    def suggest_params(self, trial: "optuna.Trial") -> Dict[str, float]:
        """Suggest parameters from Optuna trial."""
        params: Dict[str, float] = {}
        for name, spec in self._enabled_parameter_space().items():
            if spec.kind == "int":
                params[name] = trial.suggest_int(name, int(spec.low), int(spec.high))
            else:
                params[name] = trial.suggest_float(name, spec.low, spec.high)
        return params

    def apply_params_to_config(
        self,
        params: Dict[str, float],
    ) -> Dict[str, Any]:
        """
        Convert optimizer params to config overrides.

        Returns a dict suitable for ``UniverseSRConfig.global_config``.
        """
        return flat_to_nested(params)

    def evaluate_trial(
        self,
        params: Dict[str, float],
        data_map: Dict[str, Dict[str, pd.DataFrame]],
        correlation_matrix: Optional[pd.DataFrame] = None,
        bar_index: int = 0,
        eval_bars: int = 300,
    ) -> UniverseTrialResult:
        """
        Run one trial: apply params → run per-asset multi-bar eval → score.

        Uses ``MultiBarRunner`` + ``ZoneQualityEvaluator`` for each
        (asset, tf) to produce the same quality composite that Stage 2
        optimizes, ensuring both stages maximise the same objective.

        Args:
            params: Trial parameters.
            data_map: ``{asset: {tf: DataFrame}}``.
            correlation_matrix: For Tier 6 (optional).
            bar_index: Unused (kept for API compat).
            eval_bars: Number of trailing bars per asset to evaluate
                (caps wall-clock per trial).

        Returns:
            Trial result with per-asset and cross-asset scores.
        """
        from app.sr.optimization.multi_bar_runner import MultiBarRunner
        from app.sr.optimization.quality_metrics import ZoneQualityEvaluator

        config_overrides = self.apply_params_to_config(params)
        modified_global = deep_merge(self._universe_config.global_config, config_overrides)

        evaluator = ZoneQualityEvaluator()
        per_asset_scores: Dict[str, float] = {}

        for asset_cfg in self._universe_config.assets:
            symbol = asset_cfg.symbol
            timeframes = asset_cfg.timeframes or self._universe_config.default_timeframes or ["1h"]
            tf_data = data_map.get(symbol, {})

            for tf in timeframes:
                df = tf_data.get(tf)
                if df is None or len(df) < 50:
                    continue

                # Build a pipeline for this (asset, tf) with trial params
                raw_config = {
                    "asset_metadata": copy.deepcopy(modified_global.get("asset_metadata", {})),
                    "sr": copy.deepcopy(modified_global.get("sr", {})),
                    "per_tf": copy.deepcopy(modified_global.get("per_tf", {})),
                    "assets": copy.deepcopy(modified_global.get("assets", {})),
                }
                top_level = {
                    k: v for k, v in modified_global.items()
                    if k not in {"asset_metadata", "sr", "per_tf", "assets"}
                }
                if top_level:
                    raw_config["sr"] = deep_merge(raw_config["sr"], top_level)

                resolved = self._resolver.resolve(symbol, tf, raw_config)
                from app.sr.pipeline import SRv2Pipeline
                pipeline = SRv2Pipeline(resolved, asset=symbol, timeframe=tf)

                # Evaluate on trailing subset for speed
                eval_df = df.iloc[-eval_bars:] if len(df) > eval_bars else df
                runner = MultiBarRunner(pipeline)
                run_result = runner.run(eval_df)
                metrics = evaluator.evaluate(run_result)
                score = evaluator.hierarchical_score(metrics)
                key = f"{symbol}/{tf}"
                per_asset_scores[key] = score

        # Tier 6: cross-asset (if correlation matrix provided)
        cross_score = 0.0
        tier6_result: Optional[CrossAssetBenchmarkResult] = None
        if correlation_matrix is not None and len(per_asset_scores) > 1:
            # Tier 6 needs enriched zones — run the router once for cross-asset analysis
            modified_config = UniverseSRConfig(
                assets=self._universe_config.assets,
                max_workers=self._universe_config.max_workers,
                timeout_per_asset_s=self._universe_config.timeout_per_asset_s,
                default_timeframes=self._universe_config.default_timeframes,
                default_enabled_kernels=self._universe_config.default_enabled_kernels,
                global_config=modified_global,
                timeframe_overrides=self._universe_config.timeframe_overrides,
                cross_asset_enabled=self._universe_config.cross_asset_enabled,
                correlation_threshold=self._universe_config.correlation_threshold,
                min_universe_agreement=self._universe_config.min_universe_agreement,
            )
            router = UniverseSRRouter(modified_config)
            universe_result = router.process(data_map, bar_index=bar_index)
            universe_zones = self._flatten_scored_levels(universe_result)
            cross_results = self._build_cross_asset_analyzer(params).analyze(
                universe_zones, correlation_matrix,
            )
            enriched_zones = [
                ez for result in cross_results.values()
                for ez in result.enriched_zones
            ]
            bounce_rates = {
                f"{ez.scored_level.candidate.kernel_name}:{ez.scored_level.candidate.center_price:.8f}": ez.scored_level.strength
                for ez in enriched_zones
            }
            tier6_result = self._tier6.evaluate(enriched_zones, bounce_rates)
            cross_score = tier6_result.score

        # Total score
        avg_asset = sum(per_asset_scores.values()) / max(1, len(per_asset_scores))
        cfg = self._opt_config
        total = (
            avg_asset * (1.0 - cfg.tier6_weight)
            + cross_score * cfg.tier6_weight
        )

        return UniverseTrialResult(
            trial_number=0,
            params=params,
            per_asset_scores=per_asset_scores,
            cross_asset_score=cross_score,
            total_score=total,
            metadata={
                "search_space_keys": list(self._enabled_parameter_space().keys()),
                "override_keys": sorted(params.keys()),
                "optuna_available": OPTUNA_AVAILABLE,
                "tier6_participated": tier6_result is not None,
                "tier6_result": asdict(tier6_result) if tier6_result is not None else None,
            },
        )

    def optimize(
        self,
        data_map: Dict[str, Dict[str, pd.DataFrame]],
        correlation_matrix: Optional[pd.DataFrame] = None,
        callbacks: Optional[List] = None,
    ) -> UniverseOptimizationResult:
        """
        Run full optimization with Optuna.

        Before starting trials, computes data-driven bounds from the
        combined OHLCV data to tighten the search space for derivable
        kernel params.

        Args:
            data_map: ``{asset: {tf: DataFrame}}``.
            correlation_matrix: For Tier 6 evaluation.
            callbacks: Optional Optuna callbacks ``(study, trial) -> None``.

        Returns:
            Best parameters and trial history.
        """
        default_params = self._default_params()
        if not OPTUNA_AVAILABLE:
            logger.warning("Optuna not available — evaluating deterministic defaults")
            default_result = self.evaluate_trial(
                default_params,
                data_map,
                correlation_matrix,
            )
            return UniverseOptimizationResult(
                best_params=default_result.params,
                best_score=default_result.total_score,
                all_trials=[default_result],
                tier6_result=(
                    CrossAssetBenchmarkResult(**default_result.metadata["tier6_result"])
                    if default_result.metadata.get("tier6_result")
                    else None
                ),
                assets=list(data_map.keys()),
                metadata={
                    "n_trials": 1,
                    "best_trial": 0,
                    "optuna_available": False,
                    "stage1_eval_bars": self._opt_config.stage1_eval_bars,
                    "search_space_keys": list(self._enabled_parameter_space().keys()),
                },
            )

        # --- Data-driven bounds narrowing ---
        self._apply_data_driven_bounds(data_map)

        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=self._opt_config.seed),
        )

        all_trials: List[UniverseTrialResult] = []

        def objective(trial: optuna.Trial) -> float:
            params = self.suggest_params(trial)
            result = self.evaluate_trial(
                params,
                data_map,
                correlation_matrix,
                eval_bars=self._opt_config.stage1_eval_bars,
            )
            result.trial_number = trial.number
            all_trials.append(result)
            return result.total_score

        study.optimize(
            objective,
            n_trials=self._opt_config.n_trials,
            timeout=self._opt_config.timeout_s,
            callbacks=callbacks or [],
        )

        best_params = study.best_params
        best_trial_result = next(
            (trial for trial in all_trials if trial.trial_number == study.best_trial.number),
            None,
        )
        return UniverseOptimizationResult(
            best_params=best_params,
            best_score=study.best_value,
            all_trials=all_trials,
            tier6_result=(
                CrossAssetBenchmarkResult(**best_trial_result.metadata["tier6_result"])
                if best_trial_result and best_trial_result.metadata.get("tier6_result")
                else None
            ),
            assets=list(data_map.keys()),
            metadata={
                "n_trials": len(all_trials),
                "best_trial": study.best_trial.number,
                "optuna_available": True,
                "stage1_eval_bars": self._opt_config.stage1_eval_bars,
                "search_space_keys": list(self._enabled_parameter_space().keys()),
            },
        )
