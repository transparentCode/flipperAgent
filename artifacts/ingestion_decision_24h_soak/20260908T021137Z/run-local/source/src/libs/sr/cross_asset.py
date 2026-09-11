"""
Cross-Asset S/R Analyzer
=========================
Post-pipeline layer that enriches each asset's zones with
cross-asset features by comparing S/R levels across correlated
assets in the universe.

**Optional** — single-asset operation is unaffected when disabled.

This module operates on completed ``PipelineResult`` outputs from
all assets and requires a correlation matrix to filter which asset
pairs to compare.

Usage::

    analyzer = CrossAssetSRAnalyzer(config)
    enriched = analyzer.analyze(universe_results, correlation_matrix)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.sr.models import ScoredLevel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CrossAssetConfig:
    """Configuration for cross-asset S/R analysis."""
    correlation_threshold: float = 0.6
    min_universe_agreement: int = 2
    sector_cluster_eps_atr: float = 0.5
    agreement_strength_bonus: float = 0.1
    max_comparison_assets: int = 20


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class CrossAssetFeatures:
    """Cross-asset features for one zone."""
    universe_agreement_count: int = 0
    sector_cluster_score: float = 0.0
    correlation_weighted_confluence: float = 0.0
    dominant_asset_alignment: bool = False


@dataclass
class EnrichedZone:
    """A scored level enriched with cross-asset features."""
    scored_level: ScoredLevel
    cross_features: CrossAssetFeatures
    adjusted_strength: float = 0.0

    def __post_init__(self):
        if self.adjusted_strength == 0.0:
            self.adjusted_strength = self.scored_level.strength


@dataclass
class CrossAssetSRResult:
    """Cross-asset analysis result for one asset."""
    asset: str
    enriched_zones: List[EnrichedZone] = field(default_factory=list)
    compared_assets: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class CrossAssetSRAnalyzer:
    """
    Post-pipeline cross-asset S/R analysis.

    For each asset, compares its zones against zones from correlated
    assets (correlation > threshold).  Enriches with:
      - universe_agreement_count
      - sector_cluster_score
      - correlation_weighted_confluence
      - dominant_asset_alignment
    """

    def __init__(self, config: Optional[CrossAssetConfig] = None):
        self._config = config or CrossAssetConfig()

    def analyze(
        self,
        universe_zones: Dict[str, List[ScoredLevel]],
        correlation_matrix: pd.DataFrame,
        dominant_assets: Optional[List[str]] = None,
    ) -> Dict[str, CrossAssetSRResult]:
        """
        Enrich each asset's zones with cross-asset features.

        Args:
            universe_zones: ``{asset: [ScoredLevel, ...]}``
            correlation_matrix: N×N DataFrame indexed/columned by asset symbols.
            dominant_assets: Assets treated as "dominant" (e.g. SPX, BTC, DXY).

        Returns:
            ``{asset: CrossAssetSRResult}``
        """
        if dominant_assets is None:
            dominant_assets = []

        results: Dict[str, CrossAssetSRResult] = {}

        for asset, zones in universe_zones.items():
            if not zones:
                results[asset] = CrossAssetSRResult(asset=asset)
                continue

            # Find correlated assets
            correlated = self._get_correlated_assets(
                asset, correlation_matrix, universe_zones,
            )

            enriched: List[EnrichedZone] = []
            for zone in zones:
                cf = self._compute_cross_features(
                    zone, correlated, universe_zones, dominant_assets,
                )
                adjusted = self._adjust_strength(zone, cf)
                enriched.append(EnrichedZone(
                    scored_level=zone,
                    cross_features=cf,
                    adjusted_strength=adjusted,
                ))

            results[asset] = CrossAssetSRResult(
                asset=asset,
                enriched_zones=enriched,
                compared_assets=[sym for sym, _ in correlated],
                metadata={
                    "num_correlated": len(correlated),
                    "config": {
                        "threshold": self._config.correlation_threshold,
                        "min_agreement": self._config.min_universe_agreement,
                    },
                },
            )

        return results

    def _get_correlated_assets(
        self,
        asset: str,
        corr_matrix: pd.DataFrame,
        universe_zones: Dict[str, List[ScoredLevel]],
    ) -> List[Tuple[str, float]]:
        """Return [(peer_asset, correlation)] for assets above threshold."""
        if asset not in corr_matrix.index:
            return []

        row = corr_matrix.loc[asset]
        pairs = []
        for peer in row.index:
            if peer == asset:
                continue
            if peer not in universe_zones:
                continue
            corr_val = float(row[peer])
            if abs(corr_val) >= self._config.correlation_threshold:
                pairs.append((peer, corr_val))

        # Sort by correlation descending, limit
        pairs.sort(key=lambda x: abs(x[1]), reverse=True)
        return pairs[:self._config.max_comparison_assets]

    def _compute_cross_features(
        self,
        zone: ScoredLevel,
        correlated: List[Tuple[str, float]],
        universe_zones: Dict[str, List[ScoredLevel]],
        dominant_assets: List[str],
    ) -> CrossAssetFeatures:
        """Compute cross-asset features for a single zone."""
        if not correlated:
            return CrossAssetFeatures()

        zone_atr = zone.candidate.atr_at_detection
        if zone_atr <= 0:
            return CrossAssetFeatures()

        # Normalize zone price as percentage of ATR-implied recent range
        # This makes cross-asset comparison meaningful: both assets express
        # level position as "ATR-widths from center price" relative to their own scale
        zone_price = zone.candidate.center_price

        agreement_count = 0
        corr_weighted_conf = 0.0
        total_corr_weight = 0.0
        cluster_scores: List[float] = []
        dominant_aligned = False

        for peer_asset, corr_val in correlated:
            peer_zones = universe_zones.get(peer_asset, [])
            if not peer_zones:
                continue

            # Check each peer zone for alignment
            peer_matches = 0
            for pz in peer_zones:
                peer_atr = pz.candidate.atr_at_detection
                if peer_atr <= 0:
                    continue
                # Compare as ATR-distance from each zone's own center
                # Both sides normalized by their own ATR for scale-invariance
                distance_in_own_atr = abs(zone_price - pz.candidate.center_price) / zone_atr
                distance_in_peer_atr = abs(zone_price - pz.candidate.center_price) / peer_atr
                distance = min(distance_in_own_atr, distance_in_peer_atr)

                if distance <= self._config.sector_cluster_eps_atr:
                    # Within proximity — agreement
                    peer_matches += 1
                    corr_weighted_conf += abs(corr_val) * pz.strength
                    total_corr_weight += abs(corr_val)

            if peer_matches > 0:
                agreement_count += 1
                cluster_scores.append(peer_matches / max(1, len(peer_zones)))

                if peer_asset in dominant_assets:
                    dominant_aligned = True

        # Aggregate
        sector_score = float(np.mean(cluster_scores)) if cluster_scores else 0.0
        cwc = corr_weighted_conf / total_corr_weight if total_corr_weight > 0 else 0.0

        return CrossAssetFeatures(
            universe_agreement_count=agreement_count,
            sector_cluster_score=sector_score,
            correlation_weighted_confluence=cwc,
            dominant_asset_alignment=dominant_aligned,
        )

    def _adjust_strength(
        self,
        zone: ScoredLevel,
        features: CrossAssetFeatures,
    ) -> float:
        """Apply cross-asset strength bonus."""
        base = zone.strength
        bonus = 0.0

        # Bonus for universe agreement (capped at max_cross_asset_bonus)
        max_bonus = getattr(self._config, 'max_cross_asset_bonus', 0.3)
        if features.universe_agreement_count >= self._config.min_universe_agreement:
            bonus += self._config.agreement_strength_bonus * min(
                features.universe_agreement_count, 5,
            )

        # Dominant asset alignment bonus
        if features.dominant_asset_alignment:
            bonus += self._config.agreement_strength_bonus

        # Cap total bonus to prevent weak zones from being artificially inflated
        bonus = min(bonus, max_bonus)
        return min(1.0, base + bonus)
