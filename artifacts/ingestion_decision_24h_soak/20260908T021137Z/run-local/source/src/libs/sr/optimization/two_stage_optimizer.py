"""
Two-Stage S/R Optimizer Orchestrator
=====================================
Runs Stage 1 (universe-wide global) followed by Stage 2 (per-asset
kernel tuning) and produces a unified result that can be emitted
into the YAML config cascade.

Stage 1 (``UniverseSROptimizer``):
    Jointly optimizes shared structural and kernel params across the universe.

Stage 2 (``AssetSROptimizer``):
    For each (asset, tf) with sufficient data, refines per-asset kernel
    and gate params within ±bound_fraction of the Stage 1 optimum.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.sr.optimization.asset_optimizer import (
    AssetOptimizationConfig,
    AssetOptimizationResult,
    AssetSROptimizer,
)
from app.sr.optimization._shared import (
    RESULTS_DIR,
    deep_merge,
    flat_to_nested,
)
from app.sr.optimization.universe_optimizer import (
    UniverseOptimizationConfig,
    UniverseOptimizationResult,
    UniverseSROptimizer,
)
from app.sr.universe.config import UniverseSRConfig

logger = logging.getLogger(__name__)

_RESULTS_DIR = RESULTS_DIR


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class TwoStageResult:
    """Combined result from Stage 1 + Stage 2."""

    # Stage 1 global
    global_params: Dict[str, float] = field(default_factory=dict)
    global_score: float = 0.0

    # Stage 2 per-asset: asset → tf → params
    per_asset_params: Dict[str, Dict[str, Dict[str, float]]] = field(
        default_factory=dict,
    )
    per_asset_results: List[AssetOptimizationResult] = field(default_factory=list)

    # Full Stage 1 result (for deep inspection)
    stage1_result: Optional[UniverseOptimizationResult] = None

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def save(self, path: str) -> None:
        """Save result to JSON with path validation."""
        abs_path = os.path.realpath(path)
        abs_results = os.path.realpath(_RESULTS_DIR)
        if not abs_path.startswith(abs_results + os.sep) and abs_path != abs_results:
            raise ValueError(f"Save path must be under {_RESULTS_DIR}, got {path}")

        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        from app.sr.optimization._json_utils import NumpyDatetimeEncoder

        data = {
            "global_params": self.global_params,
            "global_score": self.global_score,
            "per_asset_params": self.per_asset_params,
            "per_asset_results": [
                {
                    "asset": r.asset,
                    "timeframe": r.timeframe,
                    "best_params": r.best_params,
                    "train_score": r.train_score,
                    "val_score": r.val_score,
                    "accepted": r.accepted,
                    "fallback_to_global": r.fallback_to_global,
                    "n_folds": r.n_folds,
                    "fold_scores": r.fold_scores,
                    "gate_failures": r.gate_failures,
                    "constraint_failures": r.constraint_failures,
                    "selected_kernels": r.selected_kernels,
                    "kernel_scores": r.kernel_scores,
                }
                for r in self.per_asset_results
            ],
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }
        with open(abs_path, "w") as f:
            json.dump(data, f, indent=2, cls=NumpyDatetimeEncoder)

    def apply_to_yaml(self, yaml_path: str, backup: bool = True) -> None:
        """
        Write optimized params to YAML config.

        Stage 1 global params → ``sr.*``
        Stage 2 per-asset params → ``assets.{symbol}.timeframes.{tf}.*``

        Only writes sections with optimized values; does not delete existing
        config. Creates a ``.bak`` backup by default.
        """
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
                cfg = yaml.load(f) or {}
            self._write_to_cfg(cfg)
            with open(abs_path, "w") as f:
                yaml.dump(cfg, f)
        except ImportError:
            import yaml as pyyaml
            with open(abs_path) as f:
                cfg = pyyaml.safe_load(f) or {}
            self._write_to_cfg(cfg)
            with open(abs_path, "w") as f:
                pyyaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

    def _write_to_cfg(self, cfg: dict) -> None:
        """Merge optimized params into config dict.

        When per-asset results exist, all params (global + per-asset) are
        written to per-asset/per-tf sections (``assets.{symbol}.{tf}.*``)
        to avoid polluting global ``sr.*`` defaults.  Stage 1 globals are
        merged into every optimized asset/tf pair, then Stage 2 per-asset
        params overlay on top.

        When only global params exist (no per-asset results), they are
        written to ``sr.*`` as a fallback.
        """
        # Collect all optimized asset/tf pairs from results + per_asset_params
        all_pairs: dict[str, dict[str, dict]] = {}

        # Determine target pairs: from per_asset_results first, then per_asset_params
        target_pairs: list[tuple[str, str]] = []
        if self.per_asset_results:
            target_pairs = [(r.asset, r.timeframe) for r in self.per_asset_results]
        elif self.per_asset_params:
            for asset, tf_map in self.per_asset_params.items():
                for tf in tf_map:
                    target_pairs.append((asset, tf))

        if target_pairs:
            # Write globals into each target pair's per-asset section
            if self.global_params:
                global_nested = flat_to_nested(self.global_params)
                for asset, tf in target_pairs:
                    all_pairs.setdefault(asset, {})[tf] = dict(global_nested)

            # Stage 2: overlay per-asset params (more specific)
            if self.per_asset_params:
                for asset, tf_map in self.per_asset_params.items():
                    for tf, params in tf_map.items():
                        nested = flat_to_nested(params)
                        base = all_pairs.get(asset, {}).get(tf, {})
                        all_pairs.setdefault(asset, {})[tf] = deep_merge(base, nested)

            # Write selected kernels from per-asset results
            for r in self.per_asset_results:
                if r.selected_kernels:
                    base = all_pairs.get(r.asset, {}).get(r.timeframe, {})
                    if "pipeline" not in base:
                        base["pipeline"] = {}
                    base["pipeline"]["enabled_kernels"] = list(r.selected_kernels)
                    all_pairs.setdefault(r.asset, {})[r.timeframe] = base

            # Write into config
            if "assets" not in cfg:
                cfg["assets"] = {}
            for asset, tf_map in all_pairs.items():
                if asset not in cfg["assets"]:
                    cfg["assets"][asset] = {}
                asset_section = cfg["assets"][asset]
                for tf, nested_params in tf_map.items():
                    if tf not in asset_section:
                        asset_section[tf] = {}
                    asset_section[tf] = deep_merge(asset_section[tf], nested_params)
        elif self.global_params:
            # No per-asset info at all — fall back to sr.* globals
            sr_overrides = flat_to_nested(self.global_params)
            if "sr" not in cfg:
                cfg["sr"] = {}
            cfg["sr"] = deep_merge(cfg["sr"], sr_overrides)


# Backward-compatible alias — tests import this by name
_flat_to_nested = flat_to_nested


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class TwoStageOptimizer:
    """
    Two-stage S/R optimizer orchestrator.

    Stage 1: ``UniverseSROptimizer.optimize()`` — global params.
    Stage 2: ``AssetSROptimizer.optimize()`` per (asset, tf) — kernel params.
    """

    def __init__(
        self,
        universe_config: UniverseSRConfig,
        stage1_config: Optional[UniverseOptimizationConfig] = None,
        stage2_config: Optional[AssetOptimizationConfig] = None,
    ):
        self._universe_config = universe_config
        self._stage1_config = stage1_config
        self._stage2_config = stage2_config or AssetOptimizationConfig()
        self._stage1_optimizer = UniverseSROptimizer(
            universe_config, opt_config=stage1_config,
        )

    def optimize(
        self,
        data_map: Dict[str, Dict[str, pd.DataFrame]],
        correlation_matrix: Optional[pd.DataFrame] = None,
        stage1_callbacks: Optional[List] = None,
        stage2_callbacks: Optional[List] = None,
        on_stage2_start: Optional[Any] = None,
        on_stage2_complete: Optional[Any] = None,
    ) -> TwoStageResult:
        """
        Run two-stage optimization.

        Args:
            data_map: ``{asset: {tf: DataFrame}}``.
            correlation_matrix: For Stage 1 Tier 6 evaluation.
            stage1_callbacks: Optuna callbacks for Stage 1.
            stage2_callbacks: Optuna callbacks for Stage 2.
            on_stage2_start: ``(asset, tf) -> None`` called before each Stage 2 run.
            on_stage2_complete: ``(asset, tf, result) -> None`` called after each Stage 2 run.

        Returns:
            Combined result with global + per-asset params.
        """
        start_time = time.time()

        # --- Stage 1: Global ---
        logger.info("Stage 1: Running universe-wide optimization")
        stage1_result = self._stage1_optimizer.optimize(
            data_map, correlation_matrix, callbacks=stage1_callbacks,
        )
        global_best = stage1_result.best_params
        logger.info(
            "Stage 1 complete: score=%.4f, %d params",
            stage1_result.best_score, len(global_best),
        )

        # --- Stage 2: Per-asset ---
        logger.info("Stage 2: Running per-asset optimization")
        base_raw_config = self._stage1_optimizer._build_raw_resolver_config()
        per_asset_params: Dict[str, Dict[str, Dict[str, float]]] = {}
        per_asset_results: List[AssetOptimizationResult] = []
        skipped_assets: List[str] = []

        for asset, tf_data in data_map.items():
            for tf, df in tf_data.items():
                if len(df) < self._stage2_config.min_bars:
                    logger.info(
                        "Stage 2: Skipping %s/%s — %d bars < %d min_bars",
                        asset, tf, len(df), self._stage2_config.min_bars,
                    )
                    skipped_assets.append(f"{asset}/{tf}")
                    continue

                logger.info(
                    "Stage 2: Optimizing %s/%s (%d bars)",
                    asset, tf, len(df),
                )
                if on_stage2_start is not None:
                    on_stage2_start(asset, tf)

                asset_optimizer = AssetSROptimizer(
                    asset=asset,
                    timeframe=tf,
                    global_best_params=global_best,
                    base_raw_config=base_raw_config,
                    opt_config=self._stage2_config,
                )
                asset_result = asset_optimizer.optimize(df, callbacks=stage2_callbacks)
                per_asset_results.append(asset_result)

                if on_stage2_complete is not None:
                    on_stage2_complete(asset, tf, asset_result)

                if asset not in per_asset_params:
                    per_asset_params[asset] = {}
                per_asset_params[asset][tf] = asset_result.best_params

                logger.info(
                    "Stage 2: %s/%s — accepted=%s, train=%.4f, val=%.4f",
                    asset, tf, asset_result.accepted,
                    asset_result.train_score, asset_result.val_score,
                )

        total_time = time.time() - start_time
        accepted_count = sum(1 for r in per_asset_results if r.accepted)

        return TwoStageResult(
            global_params=global_best,
            global_score=stage1_result.best_score,
            per_asset_params=per_asset_params,
            per_asset_results=per_asset_results,
            stage1_result=stage1_result,
            metadata={
                "total_time_seconds": total_time,
                "stage1_n_trials": stage1_result.metadata.get("n_trials", 0),
                "stage2_assets_optimized": len(per_asset_results),
                "stage2_assets_accepted": accepted_count,
                "stage2_assets_skipped": skipped_assets,
                "stage2_assets_total": sum(
                    len(tfs) for tfs in data_map.values()
                ),
            },
        )

    def emit_config(self, result: TwoStageResult) -> Dict[str, Any]:
        """
        Build a complete config dict from optimization results.

        Stage 1 params → ``sr.*``
        Stage 2 params → ``assets.{symbol}.{tf}.*`` (per-TF)
                       or ``assets.{symbol}.defaults.*`` (when all TFs identical)

        Returns:
            Config dict ready for YAML serialization.
        """
        config: Dict[str, Any] = {}

        # Stage 1: global params → sr.*
        if result.global_params:
            config["sr"] = flat_to_nested(result.global_params)

        # Stage 2: per-asset params
        if result.per_asset_params:
            config["assets"] = {}
            for asset, tf_map in result.per_asset_params.items():
                tfs = list(tf_map.keys())
                params_list = list(tf_map.values())

                # Check if all TFs share identical params → use defaults.*
                all_same = len(params_list) > 1 and all(
                    params_list[i] == params_list[0]
                    for i in range(1, len(params_list))
                )

                if all_same:
                    config["assets"][asset] = {
                        "defaults": flat_to_nested(params_list[0]),
                    }
                else:
                    config["assets"][asset] = {
                        tf: flat_to_nested(params)
                        for tf, params in tf_map.items()
                    }

        return config
