"""
Tier 6 Cross-Asset Benchmark
==============================
Adds a cross-asset tier that measures whether universe-agreed zones
perform better than isolated ones.

Metric: ``universe_agreement_lift`` — do zones confirmed by correlated
assets have higher bounce rates, lower false signal rates, and
better reaction quality?

Weight: 10% of total objective (Tiers 1-5 rescaled from 100% to 90%).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from app.sr.cross_asset import CrossAssetFeatures, EnrichedZone


@dataclass(frozen=True)
class CrossAssetBenchmarkResult:
    """Tier 6: Cross-asset benchmark metrics."""

    # Core metric
    universe_agreement_lift: float = 0.0  # Relative improvement of agreed zones

    # Breakdown
    agreed_zone_bounce_rate: float = 0.0
    isolated_zone_bounce_rate: float = 0.0
    agreed_zone_count: int = 0
    isolated_zone_count: int = 0
    dominant_alignment_lift: float = 0.0

    # Score [0, 1]
    score: float = 0.0


class CrossAssetBenchmark:
    """
    Computes Tier 6 cross-asset benchmark.

    Compares performance of zones with cross-asset agreement
    vs zones without.
    """

    def __init__(self, min_agreement: int = 2):
        self._min_agreement = min_agreement

    def evaluate(
        self,
        enriched_zones: List[EnrichedZone],
        zone_bounce_rates: Dict[str, float],
    ) -> CrossAssetBenchmarkResult:
        """
        Evaluate cross-asset benchmark.

        Args:
            enriched_zones: Zones with cross-asset features.
            zone_bounce_rates: ``{zone_id: bounce_rate}`` keyed by scored-level identity.

        Returns:
            Tier 6 benchmark result.
        """
        agreed: List[float] = []
        isolated: List[float] = []
        dominant_agreed: List[float] = []
        dominant_isolated: List[float] = []

        for ez in enriched_zones:
            zone_id = _zone_id(ez)
            br = zone_bounce_rates.get(zone_id, 0.0)

            if ez.cross_features.universe_agreement_count >= self._min_agreement:
                agreed.append(br)
                if ez.cross_features.dominant_asset_alignment:
                    dominant_agreed.append(br)
            else:
                isolated.append(br)
                if not ez.cross_features.dominant_asset_alignment:
                    dominant_isolated.append(br)

        agreed_br = _safe_mean(agreed)
        isolated_br = _safe_mean(isolated)

        # Lift = relative improvement
        if isolated_br > 0:
            lift = (agreed_br - isolated_br) / isolated_br
        elif agreed_br > 0:
            lift = 1.0
        else:
            lift = 0.0

        # Dominant alignment lift
        dom_agreed_br = _safe_mean(dominant_agreed)
        dom_isolated_br = _safe_mean(dominant_isolated)
        if dom_isolated_br > 0:
            dom_lift = (dom_agreed_br - dom_isolated_br) / dom_isolated_br
        elif dom_agreed_br > 0:
            dom_lift = 1.0
        else:
            dom_lift = 0.0

        # Score: normalized lift [0, 1]
        # Positive lift → good, capped at 1.0
        score = max(0.0, min(1.0, lift * 2.0))  # 50% lift → 1.0

        return CrossAssetBenchmarkResult(
            universe_agreement_lift=lift,
            agreed_zone_bounce_rate=agreed_br,
            isolated_zone_bounce_rate=isolated_br,
            agreed_zone_count=len(agreed),
            isolated_zone_count=len(isolated),
            dominant_alignment_lift=dom_lift,
            score=score,
        )


def _zone_id(ez: EnrichedZone) -> str:
    """Derive zone identity key from scored level."""
    c = ez.scored_level.candidate
    return f"{c.kernel_name}:{c.center_price:.8f}"


def _safe_mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0
