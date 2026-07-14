"""
Per-Asset Kernel Screener
==========================
Evaluates each kernel individually on asset data to determine which
kernels produce quality zones.  Used by ``AssetSROptimizer`` to build
a per-asset kernel search space.

All thresholds and parameters are configurable via the
``sr.optimization.kernel_selection`` section of sr.yaml.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.sr.config_resolver import SRConfigResolver
from app.sr.optimization.multi_bar_runner import MultiBarRunner
from app.sr.optimization.quality_metrics import ZoneQualityEvaluator, ZoneQualityMetrics
from app.sr.pipeline import SRv2Pipeline

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KernelScore:
    """Quality score for a single kernel on a specific asset."""

    kernel: str
    composite: float = 0.0
    survival_rate: float = 0.0
    touch_accuracy: float = 0.0
    false_breakout_rate: float = 0.0
    zones_created: int = 0
    passed: bool = False


@dataclass
class KernelSelectionConfig:
    """Configuration for kernel screening — loaded from yaml."""

    # Kernel counts
    min_kernels: int = 2
    max_kernels: int = 6

    # Quality floor: kernel must reach this composite to be a candidate
    min_kernel_composite: float = 0.45

    # Minimum zones: kernel must create at least this many zones
    min_kernel_zones: int = 5

    # How many top subsets to try in optimizer (categorical choices)
    max_candidate_subsets: int = 5

    # Max bars to use for screening (tail slice). 0 = use all data.
    screening_bars: int = 5000

    # Per-kernel timeout in seconds. 0 = no timeout.
    per_kernel_timeout_s: float = 120.0

    # Screening mode: "isolated" (standard), "intrinsic" (0 coverage penalty), "marginal" (gain over anchors)
    screening_mode: str = "marginal"

    # Always include these kernels (if they pass quality floor)
    anchor_kernels: List[str] = field(
        default_factory=lambda: ["pivot_hl", "volume_poc"],
    )

    @classmethod
    def from_yaml(cls, raw: Dict[str, Any]) -> "KernelSelectionConfig":
        """Build from sr.optimization.kernel_selection yaml section."""
        if not raw:
            return cls()
        return cls(
            min_kernels=raw.get("min_kernels", cls.min_kernels),
            max_kernels=raw.get("max_kernels", cls.max_kernels),
            min_kernel_composite=raw.get("min_kernel_composite", cls.min_kernel_composite),
            screening_mode=raw.get("screening_mode", cls.screening_mode),
            min_kernel_zones=raw.get("min_kernel_zones", cls.min_kernel_zones),
            max_candidate_subsets=raw.get("max_candidate_subsets", cls.max_candidate_subsets),
            screening_bars=raw.get("screening_bars", cls.screening_bars),
            per_kernel_timeout_s=raw.get("per_kernel_timeout_s", cls.per_kernel_timeout_s),
            anchor_kernels=raw.get("anchor_kernels", ["pivot_hl", "volume_poc"]),
        )


class KernelScreener:
    """
    Screen individual kernels for quality on a specific asset.

    Each kernel is run in isolation (as the only enabled_kernel) through
    the full pipeline, and scored with ``ZoneQualityEvaluator``.  Kernels
    that pass the quality floor are eligible for the optimizer's search
    space.
    """

    def __init__(
        self,
        asset: str,
        timeframe: str,
        base_raw_config: Dict[str, Any],
        config: Optional[KernelSelectionConfig] = None,
        characteristics: Any = None,
    ):
        self._asset = asset
        self._timeframe = timeframe
        self._base_raw_config = base_raw_config
        self._config = config or KernelSelectionConfig()
        self._characteristics = characteristics
        self._resolver = SRConfigResolver()
        self._evaluator = ZoneQualityEvaluator()

    def _available_kernels(self) -> List[str]:
        """Get all kernels that have config defined in sr.yaml."""
        sr = self._base_raw_config.get("sr", {})
        kernels_section = sr.get("kernels", {})
        return list(kernels_section.keys())


    def _evaluate_subset(
        self,
        kernel_names: List[str],
        df: pd.DataFrame,
        *,
        evaluator: Optional[ZoneQualityEvaluator] = None,
        start_bar: int = 0,
        max_lookback: int = 2000,
    ) -> Tuple[ZoneQualityMetrics, float, Any]:
        """Run pipeline with a subset of kernels and compute score."""
        raw_config = copy.deepcopy(self._base_raw_config)
        sr_section = raw_config.get("sr", {})
        sr_section.setdefault("pipeline", {})["enabled_kernels"] = kernel_names
        raw_config["sr"] = sr_section

        assets = raw_config.setdefault("assets", {})
        asset_cfg = assets.setdefault(self._asset, {})
        tf_cfg = asset_cfg.setdefault(self._timeframe, {})
        tf_cfg.setdefault("pipeline", {})["enabled_kernels"] = kernel_names
        
        defaults_cfg = asset_cfg.get("defaults", {})
        if defaults_cfg and "pipeline" in defaults_cfg:
            defaults_cfg["pipeline"]["enabled_kernels"] = kernel_names

        resolved = self._resolver.resolve(
            self._asset, self._timeframe, raw_config,
            characteristics=self._characteristics,
        )
        pipeline = SRv2Pipeline(resolved, asset=self._asset, timeframe=self._timeframe)
        runner = MultiBarRunner(pipeline)
        run_result = runner.run(df, start_bar=start_bar, max_lookback=max_lookback)

        ev = evaluator or self._evaluator
        metrics = ev.evaluate(run_result)
        composite = ev.composite_score(metrics)
        return metrics, composite, run_result

    def screen(self, df: pd.DataFrame, *, max_lookback: int = 2000) -> List[KernelScore]:
        """
        Evaluate each kernel and return scored list.
        Supports checking marginal vs isolated value.
        """
        available = self._available_kernels()
        scores: List[KernelScore] = []

        start_bar = 0
        limit = self._config.screening_bars
        if limit > 0 and len(df) > limit:
            start_bar = len(df) - limit
            logger.info("Kernel screening %s/%s: %s mode, %d bars",
                        self._asset, self._timeframe, self._config.screening_mode, limit)

        # Compute baseline for marginal mode (cached for anchor reuse)
        base_composite = 0.0
        self._anchor_baseline = None  # (metrics, composite, run_result)
        if self._config.screening_mode == "marginal" and self._config.anchor_kernels:
            anchors_in_avail = [k for k in self._config.anchor_kernels if k in available]
            if anchors_in_avail:
                baseline = self._evaluate_subset(
                    anchors_in_avail, df, start_bar=start_bar, max_lookback=max_lookback
                )
                self._anchor_baseline = baseline
                base_composite = baseline[1]
                logger.info("Anchor baseline composite: %.4f for %s", base_composite, anchors_in_avail)

        for kernel_name in available:
            timeout = self._config.per_kernel_timeout_s
            if timeout > 0:
                score = self._evaluate_kernel_with_timeout(
                    kernel_name, df, base_composite=base_composite,
                    start_bar=start_bar, max_lookback=max_lookback,
                    timeout_s=timeout,
                )
            else:
                score = self._evaluate_kernel(
                    kernel_name, df, base_composite=base_composite,
                    start_bar=start_bar, max_lookback=max_lookback,
                )
            scores.append(score)
            logger.info(
                "Kernel screen %s/%s kernel=%s: composite=%.4f "
                "survival=%.4f touch=%.4f zones=%d passed=%s",
                self._asset, self._timeframe, kernel_name,
                score.composite, score.survival_rate, score.touch_accuracy,
                score.zones_created, score.passed,
            )

        scores.sort(key=lambda s: s.composite, reverse=True)
        return scores

    def _evaluate_kernel_with_timeout(
        self,
        kernel_name: str,
        df: pd.DataFrame,
        *,
        base_composite: float = 0.0,
        start_bar: int = 0,
        max_lookback: int = 2000,
        timeout_s: float = 120.0,
    ) -> KernelScore:
        """Run _evaluate_kernel with a per-kernel timeout.

        Uses a daemon thread so the main process isn't blocked indefinitely
        by slow kernels (e.g. fractal_channel on large datasets).
        """
        import threading

        result_box: list = []
        error_box: list = []

        def _target() -> None:
            try:
                score = self._evaluate_kernel(
                    kernel_name, df,
                    base_composite=base_composite,
                    start_bar=start_bar,
                    max_lookback=max_lookback,
                )
                result_box.append(score)
            except Exception as exc:
                error_box.append(exc)

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        t.join(timeout=timeout_s)

        if t.is_alive():
            logger.warning(
                "Kernel screen %s/%s kernel=%s: TIMED OUT after %.0fs — skipping",
                self._asset, self._timeframe, kernel_name, timeout_s,
            )
            return KernelScore(kernel=kernel_name)

        if error_box:
            logger.exception(
                "Kernel screen %s/%s kernel=%s: error during timeout eval",
                self._asset, self._timeframe, kernel_name,
                exc_info=error_box[0],
            )
            return KernelScore(kernel=kernel_name)

        return result_box[0] if result_box else KernelScore(kernel=kernel_name)

    def _evaluate_kernel(
        self,
        kernel_name: str,
        df: pd.DataFrame,
        *,
        base_composite: float = 0.0,
        start_bar: int = 0,
        max_lookback: int = 2000,
    ) -> KernelScore:
        """Run pipeline evaluation for a specific kernel under the active mode."""
        try:
            mode = self._config.screening_mode
            
            if mode == "intrinsic":
                # Evaluate kernel alone, zero out coverage penalty
                orig_weights = dict(ZoneQualityEvaluator.DEFAULT_WEIGHTS)
                orig_weights["coverage"] = 0.0
                evaluator = ZoneQualityEvaluator(weights=orig_weights)
                metrics, composite, run_res = self._evaluate_subset(
                    [kernel_name], df, evaluator=evaluator,
                    start_bar=start_bar, max_lookback=max_lookback
                )
            elif mode == "marginal" and self._config.anchor_kernels:
                if kernel_name in self._config.anchor_kernels:
                    # Anchor kernel: reuse cached baseline to avoid redundant eval
                    if self._anchor_baseline is not None:
                        metrics, composite, run_res = self._anchor_baseline
                    else:
                        metrics, composite, run_res = self._evaluate_subset(
                            list(self._config.anchor_kernels), df,
                            start_bar=start_bar, max_lookback=max_lookback,
                        )
                else:
                    # Non-anchor: evaluate incremental value over anchor set
                    subset = list(self._config.anchor_kernels) + [kernel_name]
                    metrics, composite, run_res = self._evaluate_subset(
                        subset, df, start_bar=start_bar, max_lookback=max_lookback,
                    )
            else:
                # Isolated mode: default
                metrics, composite, run_res = self._evaluate_subset(
                    [kernel_name], df, start_bar=start_bar, max_lookback=max_lookback,
                )

            passed = (
                composite >= self._config.min_kernel_composite
                and run_res.total_zones_created >= self._config.min_kernel_zones
            )

            # In marginal mode, must actually beat the baseline
            if mode == "marginal" and kernel_name not in self._config.anchor_kernels and base_composite > 0:
                if composite <= base_composite:
                    passed = False

            return KernelScore(
                kernel=kernel_name,
                composite=composite,
                survival_rate=metrics.survival_rate,
                touch_accuracy=metrics.touch_accuracy,
                false_breakout_rate=metrics.false_breakout_rate,
                zones_created=run_res.total_zones_created,
                passed=passed,
            )
        except Exception:
            logger.exception("Kernel screen failed for %s on %s/%s", kernel_name, self._asset, self._timeframe)
            return KernelScore(kernel=kernel_name)
