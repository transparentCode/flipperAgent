"""
S/R v2 Orchestrator
====================
Coordinates the full v2 pipeline for a single (asset, timeframe) pair:

    Kernels → Features → Ensemble → Lifecycle → Output

Multi-timeframe aggregation happens outside this class: callers collect
per-timeframe ``ScoredLevel`` lists and pass them to the separate
aggregation helper when they need cross-timeframe merging.

Usage::

    from app.sr.pipeline import SRv2Pipeline

    pipeline = SRv2Pipeline(resolved_config, regime_gate=gate)
    result = pipeline.run(df, bar_index=100, timestamp=now)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from app.sr.config_schema import SRResolvedConfig
from app.sr.ensemble.base import BaseEnsembleStrategy
from app.sr.ensemble.registry import EnsembleRegistry
from app.sr.features.builder import LevelFeatureBuilder
from app.sr.features.context import FeatureContext
from app.sr.kernels import ensure_kernel_registry_populated
from app.sr.kernels.base import BaseSRKernel, KernelConfig
from app.sr.kernels.registry import KernelRegistry
from app.sr.lifecycle.state_machine import ManagedZone, ZoneLifecycleManager
from app.sr.models import (
    CandidateLevel,
    LevelFeatureVector,
    LevelType,
    ScoredLevel,
    ZoneLifecycleEvent,
    ZoneStatus,
)
from app.sr.regime_gate import RegimeGate

logger = logging.getLogger(__name__)


class PipelineKernelError(RuntimeError):
    """Raised when one or more enabled kernels fail during a pipeline run."""


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    """Output of a single pipeline run (one bar update)."""
    candidates: List[CandidateLevel]
    scored_levels: List[ScoredLevel]
    active_zones: List[ManagedZone]
    events: List[ZoneLifecycleEvent]
    new_zones: List[ManagedZone]
    ensemble_method: str
    regime_state: Optional[str] = None
    # Debug mode fields (populated when debug=True)
    debug: Optional[Dict[str, Any]] = None
    # Timing fields (populated when timing=True)
    timing: Optional[Dict[str, float]] = None


# ---------------------------------------------------------------------------
# v2 Pipeline
# ---------------------------------------------------------------------------

class SRv2Pipeline:
    """
    Full v2 SR pipeline for one (asset, timeframe) pair.

    Stateful: owns a ``ZoneLifecycleManager`` that accumulates zones
    across bar updates.  Kernels and feature builder are stateless.
    """

    def __init__(
        self,
        config: SRResolvedConfig,
        regime_gate: Optional[RegimeGate] = None,
        asset: str = "",
        timeframe: str = "",
    ):
        self._config = config
        self._asset = asset
        self._timeframe = timeframe
        # Instantiate RegimeGate with config if not provided
        self._regime_gate = regime_gate or RegimeGate(config=vars(self._config.regime))

        # Initialize kernels
        self._kernels: Dict[str, BaseSRKernel] = {}
        ensure_kernel_registry_populated()
        for name in config.pipeline.enabled_kernels:
            kernel = KernelRegistry.create(name)
            if kernel is not None:
                self._kernels[name] = kernel
            else:
                logger.warning("Kernel %s not found in registry", name)

        # Initialize ensemble
        # Ensure strategy modules are imported
        import app.sr.ensemble.weighted_average  # noqa: F401
        import app.sr.ensemble.confidence_weighted  # noqa: F401
        import app.sr.ensemble.regime_conditional  # noqa: F401

        ensemble_name = config.ensemble.method
        self._ensemble: Optional[BaseEnsembleStrategy] = EnsembleRegistry.create(
            ensemble_name,
        )
        if self._ensemble is None:
            logger.warning(
                "Ensemble %s not found, falling back to weighted_average",
                ensemble_name,
            )
            self._ensemble = EnsembleRegistry.create("weighted_average")

        # Feature builder
        self._feature_builder = LevelFeatureBuilder(config=self._config.features)

        # Lifecycle manager
        lifecycle_config = self._build_lifecycle_config()
        self._lifecycle = ZoneLifecycleManager(lifecycle_config)

        # Cross-bar dedup cache: fingerprint → last_seen_bar_index
        self._candidate_cache: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        df: pd.DataFrame,
        bar_index: int = 0,
        timestamp: Optional[datetime] = None,
        debug: bool = False,
        timing: bool = False,
    ) -> PipelineResult:
        """
        Execute the full pipeline on current OHLCV data.

        Parameters
        ----------
        df
            OHLCV DataFrame (must have at least enough bars for kernels).
        bar_index
            Current bar index (for lifecycle tracking).
        timestamp
            Current timestamp (defaults to last bar's index).
        debug
            If True, attach all intermediate states to the result.
        timing
            If True, record per-stage latency in milliseconds.
        """
        timings: Dict[str, float] = {}
        debug_info: Dict[str, Any] = {}

        if timestamp is None:
            timestamp = df.index[-1] if hasattr(df.index, '__len__') and len(df) > 0 else datetime.now(UTC)

        # Stage 1: Kernels — detect candidates
        t0 = time.perf_counter()
        all_candidates = self._run_kernels(df)
        if timing:
            timings["kernels_ms"] = (time.perf_counter() - t0) * 1000
        if debug:
            debug_info["candidates_by_kernel"] = {}
            for c in all_candidates:
                debug_info["candidates_by_kernel"].setdefault(c.kernel_name, []).append(c)

        # Stage 1b: Cross-bar dedup — suppress re-detections of same levels
        t0_dedup = time.perf_counter()
        all_candidates = self._dedup_cross_bar(all_candidates, bar_index)
        if timing:
            timings["cross_bar_dedup_ms"] = (time.perf_counter() - t0_dedup) * 1000

        # Stage 2: Features — compute feature vectors
        t0 = time.perf_counter()
        atr_period = max(1, int(self._config.pipeline.atr_period))
        avg_volume_window = max(1, int(self._config.pipeline.avg_volume_window))
        atr = BaseSRKernel.calculate_atr(df, period=atr_period)
        current_price = float(df["close"].iloc[-1])
        current_volume = float(df["volume"].iloc[-1])
        avg_volume = float(df["volume"].tail(avg_volume_window).mean())

        # Get regime state via gate
        regime_state = self._regime_gate.get_regime_or_none(
            self._asset, self._timeframe,
        )
        regime_confidence = self._regime_gate.get_confidence(
            self._asset, self._timeframe,
        )

        ctx = FeatureContext.from_dataframe(
            df,
            atr,
            regime_state=regime_state,
            regime_confidence=regime_confidence,
            volume_mean_window=self._config.features.volume_mean_window,
            volume_kurtosis_window=self._config.features.volume_kurtosis_window,
            metadata=self._config.metadata,
            timeframe=self._timeframe,
        )

        features: Dict[str, LevelFeatureVector] = {}
        for c in all_candidates:
            key = BaseEnsembleStrategy.candidate_key(c)
            fv = self._feature_builder.build(c, all_candidates, ctx)
            features[key] = fv
        if timing:
            timings["features_ms"] = (time.perf_counter() - t0) * 1000
        if debug:
            debug_info["feature_vectors"] = dict(features)
            debug_info["context"] = {
                "atr": atr,
                "atr_period": atr_period,
                "current_price": current_price,
                "current_volume": current_volume,
                "avg_volume": avg_volume,
                "avg_volume_window": avg_volume_window,
                "regime_state": regime_state,
                "regime_confidence": regime_confidence,
                "bar_count": len(df),
            }

        # Stage 3: Ensemble scoring
        t0 = time.perf_counter()
        ensemble_config = self._build_ensemble_config(regime_state)
        scored_levels = self._ensemble.score(
            all_candidates, features, ensemble_config,
        ) if self._ensemble else []
        if timing:
            timings["ensemble_ms"] = (time.perf_counter() - t0) * 1000
        if debug:
            debug_info["ensemble_config"] = ensemble_config

        # Stage 3b: Zone gate — filter weak levels + cap per bar
        scored_levels = self._apply_zone_gate(scored_levels)

        # Stage 4: Lifecycle — ingest new levels + update existing zones
        t0 = time.perf_counter()
        new_zones = self._lifecycle.ingest_scored_levels(
            scored_levels, bar_index, timestamp,
        )

        events = self._lifecycle.update(
            current_price=current_price,
            current_volume=current_volume,
            avg_volume=avg_volume,
            atr=atr,
            bar_index=bar_index,
            timestamp=timestamp,
            gap_size_atr=self._current_gap_size_atr(df, atr),
            gap_direction=self._current_gap_direction(df),
        )
        if timing:
            timings["lifecycle_ms"] = (time.perf_counter() - t0) * 1000
            timings["total_ms"] = sum(timings.values())
        if debug:
            debug_info["all_zones"] = list(self._lifecycle.all_zones)
            debug_info["lifecycle_config"] = self._build_lifecycle_config()

        return PipelineResult(
            candidates=all_candidates,
            scored_levels=scored_levels,
            active_zones=self._lifecycle.active_zones,
            events=events,
            new_zones=new_zones,
            ensemble_method=self._ensemble.strategy_name if self._ensemble else "none",
            regime_state=regime_state,
            debug=debug_info if debug else None,
            timing=timings if timing else None,
        )

    @property
    def active_zones(self) -> List[ManagedZone]:
        """Current active (non-expired) zones."""
        return self._lifecycle.active_zones

    @property
    def all_zones(self) -> List[ManagedZone]:
        """All zones including expired."""
        return self._lifecycle.all_zones

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_kernels(self, df: pd.DataFrame) -> List[CandidateLevel]:
        """Run all enabled kernels and collect candidates."""
        all_candidates: List[CandidateLevel] = []
        failed_kernels: List[str] = []
        last_error: Optional[Exception] = None
        atr_period = max(1, int(self._config.pipeline.atr_period))
        # Precompute ATR once for all kernels
        precomputed_atr = BaseSRKernel.calculate_atr(df, period=atr_period)

        for name, kernel in self._kernels.items():
            kernel_params = self._config.kernels.get(name, {})
            extra = {"asset": self._asset} if name == "regression_band" else {}
            kc = KernelConfig(
                kernel_name=name,
                timeframe=self._timeframe,
                kernel_params=kernel_params,
                metadata=self._config.metadata,
                rule_derived=self._config.rule_derived,
                extra=extra,
                atr_period=atr_period,
                precomputed_atr=precomputed_atr,
            )
            try:
                candidates = kernel.compute(df, kc)
                all_candidates.extend(candidates)
                logger.debug(
                    "Kernel %s produced %d candidates", name, len(candidates),
                )
            except Exception as exc:
                failed_kernels.append(name)
                last_error = exc
                logger.exception("Kernel %s failed", name)

        if failed_kernels:
            failed_list = ", ".join(failed_kernels)
            raise PipelineKernelError(
                f"SR pipeline aborted because kernels failed: {failed_list}",
            ) from last_error

        return self._merge_candidates(all_candidates)

    def _merge_candidates(self, candidates: List[CandidateLevel]) -> List[CandidateLevel]:
        """Spatially deduplicate candidates to avoid collinearity."""
        threshold = self._config.pipeline.merge_threshold_pct_atr
        if threshold <= 0.0 or not candidates:
            return candidates
            
        merged_candidates = []
        # Process SUPPORT and RESISTANCE separately
        for ltype in [LevelType.SUPPORT, LevelType.RESISTANCE]:
            type_cands = [c for c in candidates if c.level_type == ltype]
            if not type_cands:
                continue
                
            # Sort by raw score descending (highest quality first)
            type_cands.sort(key=lambda c: c.raw_score, reverse=True)
            
            merged = []
            for c in type_cands:
                is_duplicate = False
                atr = max(c.atr_at_detection, 1e-6)  # prevent zero-ATR disabling dedup
                for m in merged:
                    distance = abs(c.center_price - m.center_price)
                    if distance <= threshold * atr:
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    merged.append(c)
            
            merged_candidates.extend(merged)
            
        if len(merged_candidates) < len(candidates):
            logger.debug(
                "Spatial deduplication: merged %d candidates down to %d",
                len(candidates), len(merged_candidates)
            )
            
        return merged_candidates

    def _fingerprint(self, c: CandidateLevel) -> str:
        """Generate a dedup fingerprint for a candidate.

        Event-style kernels use an absolute event timestamp so sliding
        windows do not change the fingerprint as relative indices shift.
        Level-style kernels quantize price so near-identical re-detections
        across bars hash to the same key.
        """
        meta = c.metadata or {}
        origin = c.timestamp.isoformat()

        if c.kernel_name == "fair_value_gap":
            event_type = meta.get("fvg_type", c.level_type.value)
            return f"{c.kernel_name}:{event_type}:{origin}"
        if c.kernel_name == "order_block":
            event_type = meta.get("ob_type", c.level_type.value)
            return f"{c.kernel_name}:{event_type}:{origin}"
        if c.kernel_name == "liquidity_sweep":
            event_type = meta.get("sweep_type", c.level_type.value)
            return f"{c.kernel_name}:{event_type}:{origin}"

        quantize = self._config.pipeline.candidate_dedup_quantize_atr
        atr = c.atr_at_detection if c.atr_at_detection > 0 else 1.0
        bucket_size = atr * quantize
        quantized = round(c.center_price / bucket_size) if bucket_size > 0 else round(c.center_price)
        return f"{c.kernel_name}:{quantized}"

    def _dedup_cross_bar(
        self,
        candidates: List[CandidateLevel],
        bar_index: int,
    ) -> List[CandidateLevel]:
        """Suppress candidates that were already detected in recent bars.

        First-time detections always pass. Only re-detections within
        ``candidate_dedup_staleness_bars`` are suppressed.
        """
        staleness_bars = self._config.pipeline.candidate_dedup_staleness_bars
        if staleness_bars <= 0:
            return candidates

        # Evict entries once they are older than the staleness window.
        eviction_horizon = bar_index - staleness_bars
        stale_keys = [
            k for k, last_bar in self._candidate_cache.items()
            if last_bar < eviction_horizon
        ]
        for k in stale_keys:
            del self._candidate_cache[k]

        # Filter
        passed: List[CandidateLevel] = []
        for c in candidates:
            fp = self._fingerprint(c)
            last_seen = self._candidate_cache.get(fp)
            if last_seen is not None and (bar_index - last_seen) <= staleness_bars:
                # Suppressed — already seen within staleness window
                continue
            # First detection or stale enough to re-emit
            self._candidate_cache[fp] = bar_index
            passed.append(c)

        if len(passed) < len(candidates):
            logger.debug(
                "Cross-bar dedup: suppressed %d/%d candidates at bar %d",
                len(candidates) - len(passed), len(candidates), bar_index,
            )

        return passed

    def _apply_zone_gate(
        self, scored_levels: List[ScoredLevel],
    ) -> List[ScoredLevel]:
        """Filter scored levels by strength/quality threshold and per-bar cap."""
        min_strength = self._config.pipeline.min_emit_strength
        max_per_bar = self._config.pipeline.max_new_zones_per_bar
        min_quality = self._config.pipeline.min_zone_quality
        incoming = len(scored_levels)

        if min_strength > 0:
            before = len(scored_levels)
            scored_levels = [
                sl for sl in scored_levels if sl.strength >= min_strength
            ]
            if len(scored_levels) < before:
                logger.debug(
                    "Zone gate: strength filter rejected %d/%d (threshold=%.3f)",
                    before - len(scored_levels), before, min_strength,
                )

        if min_quality > 0:
            before = len(scored_levels)
            scored_levels = [
                sl for sl in scored_levels if sl.zone_quality >= min_quality
            ]
            if len(scored_levels) < before:
                logger.debug(
                    "Zone gate: quality filter rejected %d/%d (threshold=%.3f)",
                    before - len(scored_levels), before, min_quality,
                )

        if max_per_bar > 0 and len(scored_levels) > max_per_bar:
            logger.debug(
                "Zone gate: per-bar cap %d → %d",
                len(scored_levels), max_per_bar,
            )
            scored_levels = sorted(
                scored_levels,
                key=lambda sl: (sl.zone_quality, sl.strength),
                reverse=True,
            )[:max_per_bar]

        if len(scored_levels) < incoming:
            logger.debug(
                "Zone gate total: %d/%d passed",
                len(scored_levels), incoming,
            )

        return scored_levels

    def _build_ensemble_config(
        self, regime_state: Optional[str],
    ) -> Dict[str, Any]:
        """Build config dict for the ensemble strategy."""
        cfg: Dict[str, Any] = {
            "structural_vs_micro_ratio": self._config.ensemble.structural_vs_micro_ratio,
            "kernel_weights": dict(self._config.ensemble.kernel_weights),
            "structural_kernels": list(self._config.ensemble.structural_kernels),
            "micro_kernels": list(self._config.ensemble.micro_kernels),
            "confidence": dict(self._config.ensemble.confidence),
            "confidence_weighted": dict(self._config.ensemble.confidence_weighted),
            "regime_conditional": dict(self._config.ensemble.regime_conditional),
            "meta_learned": dict(self._config.ensemble.meta_learned),
            "contributing_proximity_atr": self._config.ensemble.contributing_proximity_atr,
            "zone_quality": dict(self._config.ensemble.zone_quality),
        }

        # Add regime info if available
        if regime_state is not None:
            cfg["regime_state"] = regime_state
            cfg["regime_weights"] = dict(self._config.regime.weights)
            cfg["fallback_weights"] = dict(self._config.regime.fallback_weights)

        return cfg

    def _build_lifecycle_config(self) -> Dict[str, Any]:
        """Flatten lifecycle + enhancement config for the lifecycle manager."""
        lc = self._config.lifecycle
        ec = self._config.enhancement
        rd = self._config.rule_derived

        return {
            "age_lambda": lc.age_lambda,
            "inactivity_decay": lc.inactivity_decay or rd.inactivity_decay,
            "min_strength": lc.min_strength,
            "breakout_confirm_bars": lc.breakout_confirm_bars or rd.breakout_confirm_bars,
            "false_breakout_window": lc.false_breakout_window or rd.false_breakout_window,
            "inactivity_threshold": lc.inactivity_threshold or rd.inactivity_threshold,
            "max_active_zones": lc.max_active_zones or rd.max_active_zones,
            "breakout_atr_threshold": lc.breakout_atr_threshold or rd.breakout_atr_threshold,
            "touch_proximity_atr": lc.touch_proximity_atr or rd.touch_proximity_atr,
            "false_breakout_recovery_bars": lc.false_breakout_recovery_bars or rd.false_breakout_recovery_bars,
            "stale_distance_atr": lc.stale_distance_atr,
            "max_age_bars": lc.max_age_bars,
            "flip_require_retest": lc.flip_require_retest,
            "min_touches_to_confirm": lc.min_touches_to_confirm,
            "auto_promote_kernel_agreement": lc.auto_promote_kernel_agreement,
            "dedup_proximity_atr": lc.dedup_proximity_atr,
            "false_breakout_strength_boost": lc.false_breakout_strength_boost,
            "test_held_strength_boost": lc.test_held_strength_boost,
            "merge_strength_mode": lc.merge_strength_mode,
            "min_zones_per_kernel": lc.min_zones_per_kernel,
            "enabled_kernels": list(self._config.pipeline.enabled_kernels),
            "gap_breakout_policy": self._config.metadata.gap_breakout_policy,
            "gap_escalation_atr": self._config.metadata.gap_escalation_atr,
        }

    def _current_gap_size_atr(self, df: pd.DataFrame, atr: float) -> float:
        if atr <= 0 or not self._is_current_bar_session_gap(df):
            return 0.0

        previous_close = float(df["close"].iloc[-2])
        current_open = float(df["open"].iloc[-1])
        return abs(current_open - previous_close) / atr

    def _current_gap_direction(self, df: pd.DataFrame) -> Optional[str]:
        if not self._is_current_bar_session_gap(df):
            return None

        previous_close = float(df["close"].iloc[-2])
        current_open = float(df["open"].iloc[-1])
        if current_open == previous_close:
            return None

        return "up" if current_open > previous_close else "down"

    def _is_current_bar_session_gap(self, df: pd.DataFrame) -> bool:
        if not self._config.metadata.has_session_gaps or len(df) < 2:
            return False

        deltas = df.index.to_series().diff().dropna()
        if deltas.empty:
            return False

        last_delta = deltas.iloc[-1]
        if last_delta <= pd.Timedelta(0):
            return False

        positive = deltas[deltas > pd.Timedelta(0)]
        if positive.empty:
            return False

        baseline = positive.tail(20).median()
        if baseline <= pd.Timedelta(0):
            return False

        return last_delta > baseline * 1.5
