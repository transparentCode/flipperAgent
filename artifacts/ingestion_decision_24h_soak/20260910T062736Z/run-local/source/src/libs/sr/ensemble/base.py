"""
S/R v2 Ensemble — Base Strategy ABC
====================================
All ensemble strategies implement ``score()`` to combine kernel
outputs into scored levels.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set

from app.sr.models import CandidateLevel, LevelFeatureVector, ScoredLevel


class BaseEnsembleStrategy(ABC):
    """
    Abstract base for ensemble scoring strategies.

    Stateless: receives candidates + features, returns scored levels.
    """

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """Unique identifier for this strategy."""
        ...

    @abstractmethod
    def score(
        self,
        candidates: List[CandidateLevel],
        features: Dict[str, LevelFeatureVector],
        config: Dict[str, Any],
    ) -> List[ScoredLevel]:
        """
        Score a set of candidates.

        Parameters
        ----------
        candidates
            All candidates from all kernels for one (asset, TF).
        features
            Mapping of ``candidate_key -> LevelFeatureVector``.
            Key format: ``"{kernel_name}:{center_price:.8f}"``.
        config
            Ensemble section of resolved config (structural_vs_micro_ratio,
            kernel_weights, etc.).

        Returns
        -------
        List of ``ScoredLevel`` with strength, confidence, and provenance.
        """
        ...

    @staticmethod
    def candidate_key(c: CandidateLevel) -> str:
        """Stable key for a candidate (for feature lookup)."""
        return f"{c.kernel_name}:{c.center_price:.8f}"

    @staticmethod
    def compute_standardized_confidence(
        c: CandidateLevel,
        fv: LevelFeatureVector,
        config: Dict[str, Any],
        regime_state: Optional[str] = None,
    ) -> float:
        """
        Standardized confidence calculation across all strategies.
        Represents predictive reliability based on touches, alignment, and rejection.
        """
        conf_cfg = config.get("confidence", {})
        
        touch_div = conf_cfg.get("touch_divisor", 5.0)
        agree_div = conf_cfg.get("agreement_divisor", 3.0)
        vol_div = conf_cfg.get("volume_divisor", 2.0)
        
        w_touch = conf_cfg.get("touch_weight", 0.35)
        w_agree = conf_cfg.get("agreement_weight", 0.30)
        w_rej = conf_cfg.get("rejection_weight", 0.20)
        w_vol = conf_cfg.get("volume_weight", 0.15)
        
        # Base structural confidence from features
        touch_score = min(fv.touch_count / touch_div, 1.0) if touch_div > 0 else 0.0
        agreement_score = min(fv.kernel_agreement / agree_div, 1.0) if agree_div > 0 else 0.0
        rejection_score = min(fv.rejection_ratio, 1.0)
        volume_score = min(fv.volume_at_touches / vol_div, 1.0) if (fv.volume_at_touches > 0 and vol_div > 0) else 0.0

        # Regime context adjustment (if regime is available)
        # regime_alignment in fv goes from -1.0 (opposed) to 1.0 (aligned)
        alignment = fv.regime_alignment if regime_state is not None else 0.0
        
        reg_cfg = config.get("regime_conditional", {})
        adj_factor = reg_cfg.get("confidence_adj_factor", 0.15)
        
        # Penalize confidence if opposed to regime, boost if aligned
        regime_bonus = alignment * adj_factor

        base_confidence = (
            w_touch * touch_score
            + w_agree * agreement_score
            + w_rej * rejection_score
            + w_vol * volume_score
        )
        
        return min(1.0, max(0.0, base_confidence + regime_bonus))

    @staticmethod
    def compute_zone_quality(
        strength: float,
        confidence: float,
        c: CandidateLevel,
        fv: LevelFeatureVector,
        config: Dict[str, Any],
    ) -> float:
        """
        Composite Zone Quality Score (ZQS).

        Combines strength, confidence, institutional volume alignment,
        and zone width penalty into a single [0, 1] score for position sizing.

        ZQS = w_s*strength + w_c*confidence + w_v*volume_score - w_w*width_penalty
        """
        zq_cfg = config.get("zone_quality", {})
        w_s = zq_cfg.get("strength_weight", 0.35)
        w_c = zq_cfg.get("confidence_weight", 0.30)
        w_v = zq_cfg.get("volume_weight", 0.20)
        w_w = zq_cfg.get("width_penalty_weight", 0.15)

        # Institutional volume score: POC distance + VA overlap + volume trend
        vol_score = 0.0
        if fv.value_area_overlap > 0:
            vol_score += 0.4 * min(fv.value_area_overlap, 1.0)
        if fv.poc_distance_atr > 0:
            # Closer POC = higher score (inverse)
            vol_score += 0.3 * max(0.0, 1.0 - fv.poc_distance_atr)
        if fv.volume_at_touches > 0:
            vol_score += 0.3 * min(fv.volume_at_touches / 2.0, 1.0)

        # Zone width penalty: narrow zones are higher conviction
        width = c.width_atr
        alpha = zq_cfg.get("width_decay_alpha", 3.0)
        width_penalty = 1.0 - math.exp(-alpha * width)

        raw = w_s * strength + w_c * confidence + w_v * vol_score - w_w * width_penalty
        return min(1.0, max(0.0, raw))

    @staticmethod
    def compute_confluence_tier(
        fv: LevelFeatureVector,
        contributing_kernels: List[str],
        structural_set: Set[str],
    ) -> str:
        """
        Discrete confluence tier: S, A, B, or C.

        Based on kernel agreement, MTF confluence, volume alignment,
        and touch history.
        """
        n_kernels = len(contributing_kernels)
        n_structural = sum(1 for k in contributing_kernels if k in structural_set)
        mtf_count = fv.mtf_confluence_count
        has_volume = fv.value_area_overlap > 0.2 or fv.poc_distance_atr < 0.5
        touches = fv.touch_count

        # S-tier: 3+ kernels, MTF confirmed, volume aligned, battle-tested
        if n_kernels >= 3 and mtf_count >= 2 and has_volume and touches >= 3:
            return "S"
        # A-tier: 2+ kernels (at least 1 structural), some confirmation
        if n_kernels >= 2 and n_structural >= 1 and (mtf_count >= 1 or has_volume or touches >= 2):
            return "A"
        # B-tier: 1 structural kernel, or 2+ micro with partial confirmation
        if n_structural >= 1 or (n_kernels >= 2 and (has_volume or touches >= 1)):
            return "B"
        # C-tier: everything else
        return "C"
