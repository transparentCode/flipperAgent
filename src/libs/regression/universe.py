"""Universe-level orchestrator.

Manages N assets × M timeframes:
- Resolves per-asset configs from the 4-tier hierarchy
- Maintains pipeline instances keyed by (asset, tf)
- Routes MTF cascade (top-down) for assets with mtf_enabled
- Dispatches single-TF for assets without MTF
- Shared ATR preprocessing per timeframe
- Batch-friendly: reuses pipeline instances across ticks

TASK-021: UniverseOrchestrator core
TASK-022: Batch preprocessing (shared ATR)
TASK-023: MTF cascade router
TASK-024: Asset-class dispatch (via AssetMeta on request)
TASK-025: UniverseResult wiring
TASK-026: Window authority (single source: ResolvedPipelineConfig.window_size)
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .config.resolver import ConfigResolver
from .config.schema import (
    OrchestratorConfig,
    ResolvedPipelineConfig,
    VolumeProfile,
)
from .contracts.context import (
    AssetMeta,
    CascadeContext,
    PipelineRequest,
    RegimeSnapshot,
)
from .contracts.result import (
    DegradationLevel,
    MTFOutput,
    RegressionResult,
    UniverseResult,
)
from .pipeline import RegressionPipeline
from .state import NullStateManager, StateManager

logger = logging.getLogger(__name__)


class UniverseOrchestrator:
    """Batch orchestrator for universe-wide regression.

    Lifecycle:
        1. Construct with ConfigResolver (or YAML path / dict).
        2. Call ``process_universe()`` each tick with data for all assets.
        3. Pipeline instances are cached and reused across ticks.
    """

    def __init__(
        self,
        resolver: ConfigResolver,
        state_manager: Optional[StateManager] = None,
        max_workers: int = 4,
    ) -> None:
        self._resolver = resolver
        self._state_manager = state_manager or NullStateManager()
        self._max_workers = max_workers

        # Pipeline cache: (asset, tf) → RegressionPipeline
        self._pipelines: Dict[tuple, RegressionPipeline] = {}

        # AssetMeta cache: asset → AssetMeta
        self._asset_meta: Dict[str, AssetMeta] = {}

        # Orchestrator config ref
        self._orch = resolver.orchestrator_config

    @classmethod
    def from_yaml(
        cls, path: str, state_manager: Optional[StateManager] = None, max_workers: int = 4
    ) -> "UniverseOrchestrator":
        resolver = ConfigResolver.from_yaml(path)
        return cls(resolver, state_manager, max_workers)

    @classmethod
    def from_dict(
        cls, raw: Dict[str, Any], state_manager: Optional[StateManager] = None, max_workers: int = 4
    ) -> "UniverseOrchestrator":
        resolver = ConfigResolver.from_dict(raw)
        return cls(resolver, state_manager, max_workers)

    # ── Public API ──

    def process_universe(
        self,
        universe_data: Dict[str, Dict[str, pd.DataFrame]],
        regime_data: Optional[Dict[str, RegimeSnapshot]] = None,
        mode: str = "fit_last",
    ) -> UniverseResult:
        """Process all assets in the universe.

        Args:
            universe_data: {asset: {timeframe: DataFrame}} for each asset and TF.
            regime_data: Optional {asset: RegimeSnapshot} for regime-aware windowing.
            mode: "fit_last" (live tick) or "fit_series" (backtest).

        Returns:
            UniverseResult with per-asset results and statistics.
        """
        t0 = time.perf_counter()

        results: Dict[str, RegressionResult] = {}
        mtf_results: Dict[str, MTFOutput] = {}
        n_degraded = 0
        n_failed = 0

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = []
            for asset, tf_data in universe_data.items():
                regime = regime_data.get(asset) if regime_data else None
                futures.append(
                    executor.submit(self._process_asset_task, asset, tf_data, regime, mode)
                )

            for future in as_completed(futures):
                asset, mtf_out, result = future.result()
                results[asset] = result
                
                if mtf_out is not None:
                    mtf_results[asset] = mtf_out
                    if mtf_out.degradation == DegradationLevel.FAILED:
                        n_failed += 1
                    elif mtf_out.degradation != DegradationLevel.FULL:
                        n_degraded += 1
                else:
                    if result.degradation == DegradationLevel.FAILED:
                        n_failed += 1
                    elif result.degradation != DegradationLevel.FULL:
                        n_degraded += 1

        elapsed_ms = (time.perf_counter() - t0) * 1000

        return UniverseResult(
            results=results,
            mtf_results=mtf_results,
            n_assets_processed=len(universe_data),
            n_degraded=n_degraded,
            n_failed=n_failed,
            processing_time_ms=elapsed_ms,
            config_hash=self._universe_config_hash(list(universe_data.keys())),
        )

    def process_asset(
        self,
        asset: str,
        tf_data: Dict[str, pd.DataFrame],
        regime: Optional[RegimeSnapshot] = None,
        mode: str = "fit_last",
    ) -> RegressionResult:
        """Process a single asset (convenience for single-asset use)."""
        _, _, result = self._process_asset_task(asset, tf_data, regime, mode)
        return result

    def _process_asset_task(
        self,
        asset: str,
        tf_data: Dict[str, pd.DataFrame],
        regime: Optional[RegimeSnapshot],
        mode: str,
    ) -> tuple[str, Optional[MTFOutput], RegressionResult]:
        """Helper for threaded asset processing."""
        asset_meta = self._resolve_asset_meta(asset)
        sample_tf = next(iter(tf_data))
        config = self._get_or_create_config(asset, sample_tf)

        if config.mtf_enabled and len(tf_data) > 1:
            mtf_out = self._run_mtf_cascade(asset, tf_data, regime, asset_meta, mode)
            return asset, mtf_out, mtf_out.dominant_result

        tf = next(iter(tf_data))
        result = self._run_single_tf(asset, tf, tf_data[tf], regime, asset_meta, mode)
        return asset, None, result

    def reset(self, asset: Optional[str] = None) -> None:
        """Reset pipeline state. If asset given, reset only that asset's pipelines."""
        if asset is not None:
            for key, pipeline in list(self._pipelines.items()):
                if key[0] == asset:
                    pipeline.reset()
        else:
            for pipeline in self._pipelines.values():
                pipeline.reset()

    @property
    def active_pipelines(self) -> int:
        return len(self._pipelines)

    # ── MTF Cascade ──

    def _run_mtf_cascade(
        self,
        asset: str,
        tf_data: Dict[str, pd.DataFrame],
        regime: Optional[RegimeSnapshot],
        asset_meta: AssetMeta,
        mode: str,
    ) -> MTFOutput:
        """Run top-down MTF cascade: highest TF first, propagate CascadeContext down."""
        config = self._get_or_create_config(asset, next(iter(tf_data)))
        ordered_tfs = [tf for tf in config.mtf_timeframes if tf in tf_data]

        if not ordered_tfs:
            ordered_tfs = list(tf_data.keys())

        per_tf: Dict[str, RegressionResult] = {}
        cascade: Optional[CascadeContext] = None

        # Top-down: run highest TF first
        for tf in ordered_tfs:
            df = tf_data[tf]
            result = self._run_single_tf(asset, tf, df, regime, asset_meta, mode, cascade=cascade)
            per_tf[tf] = result

            # Build cascade context for next (lower) TF
            if result.is_valid:
                cascade = CascadeContext(
                    source_tf=tf,
                    slope=result.slope,
                    direction=result.direction,
                    confidence=result.confidence,
                    band_width=result.band_width_avg,
                    dominant_method=result.ensemble_result.dominant_method,
                )

        return self._build_mtf_output(asset, per_tf)

    def _build_mtf_output(
        self, asset: str, per_tf: Dict[str, RegressionResult]
    ) -> MTFOutput:
        """Aggregate per-TF results into MTFOutput with alignment scoring."""
        tf_weights = self._orch.tf_weights

        valid_tfs = {tf: r for tf, r in per_tf.items() if r.is_valid}

        if not valid_tfs:
            first_result = next(iter(per_tf.values()))
            return MTFOutput(
                asset=asset,
                per_tf=per_tf,
                alignment_score=0.0,
                direction_consensus="NEUTRAL",
                consensus_strength=0.0,
                dominant_tf=next(iter(per_tf)),
                dominant_result=first_result,
                is_conflicted=True,
                conflict_pairs=[],
                weighted_slope=0.0,
                weighted_confidence=0.0,
                all_warmed_up=False,
                degradation=DegradationLevel.FAILED,
            )

        # Weighted slope & confidence
        total_w = 0.0
        w_slope = 0.0
        w_conf = 0.0
        for tf, result in valid_tfs.items():
            w = tf_weights.get(tf, 1.0 / len(valid_tfs))
            w_slope += result.slope * w
            w_conf += result.confidence * w
            total_w += w

        if total_w > 0:
            weighted_slope = w_slope / total_w
            weighted_confidence = w_conf / total_w
        else:
            weighted_slope = 0.0
            weighted_confidence = 0.0

        # Direction consensus
        directions = [r.direction for r in valid_tfs.values()]
        bullish_count = directions.count("BULLISH")
        bearish_count = directions.count("BEARISH")
        total = len(directions)

        if bullish_count == total:
            direction_consensus = "BULLISH"
            consensus_strength = 1.0
        elif bearish_count == total:
            direction_consensus = "BEARISH"
            consensus_strength = 1.0
        elif bullish_count > bearish_count:
            direction_consensus = "BULLISH"
            consensus_strength = bullish_count / total
        elif bearish_count > bullish_count:
            direction_consensus = "BEARISH"
            consensus_strength = bearish_count / total
        else:
            direction_consensus = "NEUTRAL"
            consensus_strength = 0.0

        # Alignment score: [-1, +1]. +1 = all same direction, -1 = all opposed
        if total > 1:
            agreement = max(bullish_count, bearish_count) / total
            alignment = agreement * 2 - 1  # map [0.5, 1.0] → [0.0, 1.0]
            if bullish_count > 0 and bearish_count > 0:
                alignment = -alignment  # conflict → negative
        else:
            alignment = 1.0

        # Conflict pairs
        conflict_pairs = []
        tf_list = list(valid_tfs.keys())
        for i in range(len(tf_list)):
            for j in range(i + 1, len(tf_list)):
                d_i = valid_tfs[tf_list[i]].direction
                d_j = valid_tfs[tf_list[j]].direction
                if d_i != d_j and d_i != "NEUTRAL" and d_j != "NEUTRAL":
                    conflict_pairs.append((tf_list[i], tf_list[j]))

        # Dominant TF: highest weighted confidence
        dominant_tf = max(valid_tfs, key=lambda tf: tf_weights.get(tf, 0) * valid_tfs[tf].confidence)

        all_warmed = all(r.is_warmed_up for r in per_tf.values())

        degradation = DegradationLevel.FULL
        if len(valid_tfs) < len(per_tf):
            degradation = DegradationLevel.PARTIAL
        if not valid_tfs:
            degradation = DegradationLevel.FAILED

        return MTFOutput(
            asset=asset,
            per_tf=per_tf,
            alignment_score=float(alignment),
            direction_consensus=direction_consensus,
            consensus_strength=float(consensus_strength),
            dominant_tf=dominant_tf,
            dominant_result=valid_tfs[dominant_tf],
            is_conflicted=len(conflict_pairs) > 0,
            conflict_pairs=conflict_pairs,
            weighted_slope=float(weighted_slope),
            weighted_confidence=float(weighted_confidence),
            all_warmed_up=all_warmed,
            degradation=degradation,
        )

    # ── Single-TF Execution ──

    def _run_single_tf(
        self,
        asset: str,
        tf: str,
        df: pd.DataFrame,
        regime: Optional[RegimeSnapshot],
        asset_meta: AssetMeta,
        mode: str,
        cascade: Optional[CascadeContext] = None,
    ) -> RegressionResult:
        """Run pipeline for a single (asset, tf)."""
        pipeline = self._get_or_create_pipeline(asset, tf)
        config = pipeline.config

        # Populate regime.suggested_window from defaults if not set
        if (
            regime is not None
            and regime.suggested_window is None
            and regime.label in self._orch.regime_window_defaults
        ):
            regime = RegimeSnapshot(
                label=regime.label,
                confidence=regime.confidence,
                transition_prob=regime.transition_prob,
                suggested_window=self._orch.regime_window_defaults[regime.label],
                metadata=regime.metadata,
            )

        request = PipelineRequest(
            df=df,
            asset=asset,
            timeframe=tf,
            mode=mode,
            config=config,
            regime=regime,
            cascade=cascade,
            asset_meta=asset_meta,
        )

        if mode == "fit_series":
            results = pipeline.compute_series(request)
            return results[-1] if results else pipeline._empty_result(
                request, request.resolve_window(), DegradationLevel.FAILED
            )

        return pipeline.compute(request)

    # ── Pipeline & Config Management ──

    def _get_or_create_pipeline(self, asset: str, tf: str) -> RegressionPipeline:
        key = (asset, tf)
        if key not in self._pipelines:
            config = self._get_or_create_config(asset, tf)
            self._pipelines[key] = RegressionPipeline(
                config, self._state_manager, validate=True
            )
        return self._pipelines[key]

    def _get_or_create_config(self, asset: str, tf: str) -> ResolvedPipelineConfig:
        return self._resolver.resolve(asset, tf)

    def _resolve_asset_meta(self, asset: str) -> AssetMeta:
        if asset in self._asset_meta:
            return self._asset_meta[asset]

        asset_cfg = self._orch.assets.get(asset)
        if asset_cfg is None:
            meta = AssetMeta(
                asset_class="crypto",
                volume_profile=VolumeProfile.CONTINUOUS,
            )
        else:
            ac_name = asset_cfg.asset_class
            ac_cfg = self._orch.asset_classes.get(ac_name)    
            if ac_cfg is not None:
                meta = AssetMeta(
                    asset_class=ac_name,
                    volume_profile=ac_cfg.volume_profile,
                    session_gap_handling=ac_cfg.session_gap_handling,
                    low_liquidity_window_handling=ac_cfg.low_liquidity_window_handling,
                )
            else:
                meta = AssetMeta(
                    asset_class=ac_name,
                    volume_profile=VolumeProfile.CONTINUOUS,
                )

        self._asset_meta[asset] = meta
        return meta

    def _universe_config_hash(self, assets: List[str]) -> str:
        """Compute a hash representing the universe configuration."""
        import hashlib
        parts = []
        for asset in sorted(assets):
            for tf in self._orch.mtf_timeframes:
                cfg = self._resolver.resolve(asset, tf)
                parts.append(cfg.config_hash)
        combined = "|".join(parts)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]
