"""
Asset Qualifier
================
Ranks assets cross-sectionally on structural metrics and assigns
confidence tiers.

Design principles:
  - **Relative ranking**: no absolute thresholds. Assets are compared
    to each other within the universe, not against magic numbers.
  - **Config-driven**: tier boundaries, confidence weights, and metric
    weights all come from ``sr.qualification`` in sr.yaml.
  - **Self-calibrating**: if the whole universe degrades, all assets
    shift down proportionally — no fixed gate to game.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from app.sr.qualification.screener import StructuralMetrics

logger = logging.getLogger("app.sr.qualification")


@dataclass(frozen=True)
class QualificationResult:
    """Qualification outcome for one (asset, timeframe)."""

    asset: str
    timeframe: str
    # Structural metrics (raw values)
    metrics: StructuralMetrics
    # Per-metric percentile ranks [0, 1] — higher = better
    metric_ranks: Dict[str, float] = field(default_factory=dict)
    # Weighted composite rank [0, 1] — higher = better
    composite_rank: float = 0.0
    # Tier assignment: 1 (best) to N (worst)
    tier: int = 4
    # Confidence weight for downstream consumers
    confidence_weight: float = 0.15
    # Optimization trials allocated
    optimization_trials: int = 0


@dataclass
class UniverseQualificationReport:
    """Full qualification report for the universe."""

    results: List[QualificationResult] = field(default_factory=list)
    universe_size: int = 0

    def by_tier(self, tier: int) -> List[QualificationResult]:
        """Filter results by tier."""
        return [r for r in self.results if r.tier == tier]

    def get(self, asset: str, timeframe: str) -> Optional[QualificationResult]:
        """Look up a specific (asset, timeframe)."""
        for r in self.results:
            if r.asset == asset and r.timeframe == timeframe:
                return r
        return None

    def summary_table(self) -> str:
        """Human-readable summary table."""
        lines = [
            f"Universe Qualification Report ({self.universe_size} asset-timeframe pairs)",
            "-" * 80,
            f"{'Asset':<12} {'TF':<4} {'Tier':>4} {'Weight':>7} "
            f"{'Rank':>6} {'POC_CV':>8} {'Wick':>6} {'Surv':>6} {'Trials':>7}",
            "-" * 80,
        ]
        for r in sorted(self.results, key=lambda x: x.composite_rank, reverse=True):
            m = r.metrics
            lines.append(
                f"{r.asset:<12} {r.timeframe:<4} Q{r.tier:>3} {r.confidence_weight:>7.2f} "
                f"{r.composite_rank:>6.3f} "
                f"{m.poc_stability or 0:>8.4f} "
                f"{m.wick_body_ratio or 0:>6.2f} "
                f"{m.quick_survival or 0:>6.2f} "
                f"{r.optimization_trials:>7}"
            )
        lines.append("-" * 80)
        # Tier summary
        for tier_num in range(1, len(self._tier_counts()) + 1):
            count = self._tier_counts().get(tier_num, 0)
            lines.append(f"  Q{tier_num}: {count} assets")
        return "\n".join(lines)

    def _tier_counts(self) -> Dict[int, int]:
        counts: Dict[int, int] = {}
        for r in self.results:
            counts[r.tier] = counts.get(r.tier, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSON/YAML output."""
        return {
            "universe_size": self.universe_size,
            "results": [
                {
                    "asset": r.asset,
                    "timeframe": r.timeframe,
                    "tier": r.tier,
                    "confidence_weight": r.confidence_weight,
                    "composite_rank": round(r.composite_rank, 4),
                    "optimization_trials": r.optimization_trials,
                    "metrics": {
                        "poc_stability": round(r.metrics.poc_stability, 6) if r.metrics.poc_stability is not None else None,
                        "wick_body_ratio": round(r.metrics.wick_body_ratio, 4) if r.metrics.wick_body_ratio is not None else None,
                        "quick_survival": round(r.metrics.quick_survival, 4) if r.metrics.quick_survival is not None else None,
                        "bar_count": r.metrics.bar_count,
                    },
                    "metric_ranks": {k: round(v, 4) for k, v in r.metric_ranks.items()},
                    "errors": r.metrics.errors if r.metrics.errors else None,
                }
                for r in sorted(self.results, key=lambda x: x.composite_rank, reverse=True)
            ],
        }


class AssetQualifier:
    """Cross-sectional ranker and tier assigner.

    Takes a list of :class:`StructuralMetrics` and produces
    :class:`QualificationResult` per (asset, timeframe) using
    relative ranking — no absolute thresholds.

    Parameters
    ----------
    config : dict
        The ``sr.qualification`` section from sr.yaml.
    """

    def __init__(self, config: Dict[str, Any]):
        self._config = config
        self._metrics_config = config.get("metrics", {})
        self._tiers_config = config.get("tiers", {})

        # Tier boundaries and weights from config
        self._boundaries = self._tiers_config.get("boundaries", [0.25, 0.50, 0.75])
        self._confidence_weights = self._tiers_config.get(
            "confidence_weights", [1.0, 0.7, 0.4, 0.15]
        )
        self._optimization_trials = self._tiers_config.get(
            "optimization_trials", [150, 100, 50, 0]
        )

    def qualify(
        self, metrics_list: List[StructuralMetrics]
    ) -> UniverseQualificationReport:
        """Rank and tier all assets in the universe.

        Parameters
        ----------
        metrics_list : list of StructuralMetrics
            Raw metrics from :class:`StructuralScreener` for every
            (asset, timeframe) in the universe.

        Returns
        -------
        UniverseQualificationReport
        """
        if not metrics_list:
            return UniverseQualificationReport()

        # Collect enabled metric names and their config
        enabled_metrics = self._get_enabled_metrics()
        if not enabled_metrics:
            logger.warning("No metrics enabled in qualification config")
            return UniverseQualificationReport(universe_size=len(metrics_list))

        # Extract raw values per metric
        raw_values = self._extract_raw_values(metrics_list, enabled_metrics)

        # Compute percentile ranks per metric
        all_ranks = self._compute_ranks(metrics_list, raw_values, enabled_metrics)

        # Compute weighted composite rank
        composite_ranks = self._compute_composite_ranks(
            metrics_list, all_ranks, enabled_metrics
        )

        # Assign tiers based on composite rank percentile
        results = self._assign_tiers(metrics_list, all_ranks, composite_ranks)

        report = UniverseQualificationReport(
            results=results,
            universe_size=len(metrics_list),
        )
        logger.info(
            "Qualified %d asset-timeframe pairs into %d tiers",
            len(metrics_list),
            len(set(r.tier for r in results)),
        )
        return report

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _get_enabled_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Return {metric_name: config} for enabled metrics."""
        enabled = {}
        for name, cfg in self._metrics_config.items():
            if isinstance(cfg, dict) and cfg.get("enabled", False):
                enabled[name] = cfg
        return enabled

    @staticmethod
    def _extract_raw_values(
        metrics_list: List[StructuralMetrics],
        enabled_metrics: Dict[str, Dict[str, Any]],
    ) -> Dict[str, List[Optional[float]]]:
        """Extract raw metric values in list order."""
        raw: Dict[str, List[Optional[float]]] = {}
        for name in enabled_metrics:
            raw[name] = [getattr(m, name, None) for m in metrics_list]
        return raw

    @staticmethod
    def _percentile_rank(
        values: List[Optional[float]], ascending: bool = True
    ) -> List[float]:
        """Compute percentile ranks for a list of values.

        Handles None values by assigning them rank 0 (worst).
        Returns ranks in [0, 1] where 1 = best.

        Parameters
        ----------
        values : list
            Raw metric values (may contain None).
        ascending : bool
            If True, lower values get higher ranks (e.g., POC stability).
            If False, higher values get higher ranks (e.g., survival rate).
        """
        n = len(values)
        if n == 0:
            return []
        if n == 1:
            return [1.0 if values[0] is not None else 0.0]

        # Separate valid from None
        indexed = [(i, v) for i, v in enumerate(values) if v is not None]
        ranks = [0.0] * n

        if not indexed:
            return ranks

        # Sort by value
        indexed.sort(key=lambda x: x[1], reverse=not ascending)

        # Assign ranks with tie-handling (average rank for ties)
        sorted_count = len(indexed)
        i = 0
        while i < sorted_count:
            # Find tie group
            j = i
            while j < sorted_count and indexed[j][1] == indexed[i][1]:
                j += 1
            # Average rank for tie group
            avg_rank = sum(range(i, j)) / (j - i)
            # Normalize to [0, 1]
            normalized = 1.0 - (avg_rank / max(1, sorted_count - 1))
            for k in range(i, j):
                ranks[indexed[k][0]] = normalized
            i = j

        return ranks

    def _compute_ranks(
        self,
        metrics_list: List[StructuralMetrics],
        raw_values: Dict[str, List[Optional[float]]],
        enabled_metrics: Dict[str, Dict[str, Any]],
    ) -> Dict[str, List[float]]:
        """Compute percentile ranks for each metric."""
        all_ranks: Dict[str, List[float]] = {}
        for name, cfg in enabled_metrics.items():
            ascending = cfg.get("rank_direction", "asc") == "asc"
            all_ranks[name] = self._percentile_rank(
                raw_values[name], ascending=ascending
            )
        return all_ranks

    def _compute_composite_ranks(
        self,
        metrics_list: List[StructuralMetrics],
        all_ranks: Dict[str, List[float]],
        enabled_metrics: Dict[str, Dict[str, Any]],
    ) -> List[float]:
        """Weighted average of per-metric ranks."""
        n = len(metrics_list)
        weights = {name: cfg.get("weight", 1.0) for name, cfg in enabled_metrics.items()}
        total_weight = sum(weights.values())
        if total_weight == 0:
            return [0.0] * n

        composites = []
        for i in range(n):
            weighted_sum = sum(
                all_ranks[name][i] * weights[name]
                for name in enabled_metrics
            )
            composites.append(weighted_sum / total_weight)
        return composites

    def _assign_tiers(
        self,
        metrics_list: List[StructuralMetrics],
        all_ranks: Dict[str, List[float]],
        composite_ranks: List[float],
    ) -> List[QualificationResult]:
        """Assign tiers based on composite rank percentile within the universe."""
        n = len(metrics_list)

        # Sort composite ranks to find percentile thresholds
        sorted_composites = sorted(composite_ranks, reverse=True)
        tier_thresholds = []
        for boundary in self._boundaries:
            idx = min(int(boundary * n), n - 1)
            tier_thresholds.append(sorted_composites[idx])

        results = []
        for i, m in enumerate(metrics_list):
            comp_rank = composite_ranks[i]

            # Determine tier: find first threshold the rank falls below
            tier = 1
            for t_idx, threshold in enumerate(tier_thresholds):
                if comp_rank < threshold:
                    tier = t_idx + 2
                else:
                    break

            # Clamp tier to valid range
            max_tier = len(self._confidence_weights)
            tier = min(tier, max_tier)

            # Look up confidence weight and trials from config
            weight_idx = tier - 1
            conf_weight = (
                self._confidence_weights[weight_idx]
                if weight_idx < len(self._confidence_weights)
                else self._confidence_weights[-1]
            )
            opt_trials = (
                self._optimization_trials[weight_idx]
                if weight_idx < len(self._optimization_trials)
                else self._optimization_trials[-1]
            )

            metric_ranks = {
                name: all_ranks[name][i]
                for name in all_ranks
            }

            results.append(
                QualificationResult(
                    asset=m.asset,
                    timeframe=m.timeframe,
                    metrics=m,
                    metric_ranks=metric_ranks,
                    composite_rank=comp_rank,
                    tier=tier,
                    confidence_weight=conf_weight,
                    optimization_trials=opt_trials,
                )
            )

        return results
