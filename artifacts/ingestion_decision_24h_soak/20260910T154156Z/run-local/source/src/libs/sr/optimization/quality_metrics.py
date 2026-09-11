"""
Zone Quality Metrics
=====================
Evaluates zone lifecycle outcomes from a multi-bar pipeline run.

Metrics:
  - survival_rate: fraction of created zones that reached ACTIVE
  - touch_accuracy: fraction of touches that produced a bounce
  - false_breakout_rate: fraction of breakouts that reversed (lower is better)
  - strength_stability: 1 - cv(strength) across final zones
  - coverage: fraction of significant price reversals near a zone

Used by ``AssetSROptimizer`` as the multi-bar objective function.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

from app.sr.optimization.multi_bar_runner import MultiBarRunResult


@dataclass(frozen=True)
class ZoneQualityMetrics:
    """Quality scores from a multi-bar evaluation, all in [0, 1]."""

    survival_rate: float = 0.0
    touch_accuracy: float = 0.0
    false_breakout_rate: float = 0.0  # lower is better
    strength_stability: float = 0.0
    coverage: float = 0.0


class ZoneQualityEvaluator:
    """
    Computes quality metrics from ``MultiBarRunResult``.

    Default composite weights:
        survival 0.25, touch_accuracy 0.30, false_breakout_rate 0.20,
        strength_stability 0.10, coverage 0.15
    """

    DEFAULT_WEIGHTS = {
        "survival_rate": 0.25,
        "touch_accuracy": 0.30,
        "false_breakout_rate": 0.20,
        "strength_stability": 0.10,
        "coverage": 0.15,
    }

    def __init__(
        self,
        weights: Optional[dict] = None,
        reversal_threshold_pct: float = 0.015,
        coverage_proximity_atr: float = 0.3,
    ):
        self._weights = weights or dict(self.DEFAULT_WEIGHTS)
        self._reversal_threshold_pct = reversal_threshold_pct
        self._coverage_proximity_atr = coverage_proximity_atr

    def evaluate(self, run_result: MultiBarRunResult) -> ZoneQualityMetrics:
        """Compute all quality metrics from a multi-bar run."""
        return ZoneQualityMetrics(
            survival_rate=self._survival_rate(run_result),
            touch_accuracy=self._touch_accuracy(run_result),
            false_breakout_rate=self._false_breakout_rate(run_result),
            strength_stability=self._strength_stability(run_result),
            coverage=self._coverage(run_result),
        )

    def composite_score(self, metrics: ZoneQualityMetrics) -> float:
        """
        Weighted composite score in [0, 1].

        ``false_breakout_rate`` is inverted (lower rate = higher score).
        """
        w = self._weights
        return (
            w["survival_rate"] * metrics.survival_rate
            + w["touch_accuracy"] * metrics.touch_accuracy
            + w["false_breakout_rate"] * (1.0 - metrics.false_breakout_rate)
            + w["strength_stability"] * metrics.strength_stability
            + w["coverage"] * metrics.coverage
        )

    def hierarchical_score(
        self,
        metrics: ZoneQualityMetrics,
        *,
        min_coverage: float = 0.03,
        min_survival: float = 0.15,
        gate_floor: float = 0.10,
        secondary_weight: float = 0.15,
    ) -> float:
        """Hierarchical objective with hard gates and focused primary metric.

        1. **Gate**: if coverage or survival below floor, return a penalty
           score proportional to how far below (never exceeds ``gate_floor``).
        2. **Primary** (weight ``1 - secondary_weight``):
           ``touch_accuracy × (1 - false_breakout_rate)`` — the single
           metric measuring zone prediction quality.
        3. **Secondary** (weight ``secondary_weight``):
           ``0.5 × coverage + 0.3 × strength_stability + 0.2 × survival_rate``
           — tiebreaker among configs with similar primary scores.

        Returns a score in [0, 1].
        """
        # Gate: hard floor on coverage and survival
        if metrics.coverage < min_coverage or metrics.survival_rate < min_survival:
            # Proportional penalty so Optuna can still learn direction
            cov_ratio = metrics.coverage / max(min_coverage, 1e-9)
            surv_ratio = metrics.survival_rate / max(min_survival, 1e-9)
            return gate_floor * min(cov_ratio, surv_ratio)

        # Primary: zone prediction quality
        primary = metrics.touch_accuracy * (1.0 - metrics.false_breakout_rate)

        # Secondary: tiebreaker
        secondary = (
            0.5 * metrics.coverage
            + 0.3 * metrics.strength_stability
            + 0.2 * metrics.survival_rate
        )

        score = (1.0 - secondary_weight) * primary + secondary_weight * secondary
        return min(1.0, max(0.0, score))

    # ------------------------------------------------------------------
    # Individual metrics
    # ------------------------------------------------------------------

    @staticmethod
    def _survival_rate(r: MultiBarRunResult) -> float:
        """Fraction of created zones that reached ACTIVE."""
        if r.total_zones_created == 0:
            return 0.0
        return min(1.0, r.zones_reached_active / r.total_zones_created)

    @staticmethod
    def _touch_accuracy(r: MultiBarRunResult) -> float:
        """
        Fraction of touches where the zone survived (bounced) rather than
        immediately breaking out.

        For each touch event, look at the *next* event for the same zone.
        If that next event is a breakout, the touch failed; otherwise
        (another touch, expiry, or no further event) the touch held.
        """
        if r.total_touches == 0:
            return 0.0

        # Build ordered list of events per zone
        zone_events: dict[str, list[str]] = {}
        for ev in r.all_events:
            zone_events.setdefault(ev.zone_id, []).append(ev.trigger)

        bounces = 0
        total = 0
        for zone_id, triggers in zone_events.items():
            for i, trig in enumerate(triggers):
                if trig not in ("touch", "touch_confirm"):
                    continue
                total += 1
                # Check what happens next for this zone
                next_trig = triggers[i + 1] if i + 1 < len(triggers) else None
                if next_trig is None or not next_trig.startswith("breakout_"):
                    bounces += 1

        if total == 0:
            return 0.0
        return min(1.0, bounces / total)

    @staticmethod
    def _false_breakout_rate(r: MultiBarRunResult) -> float:
        """Fraction of breakouts that reversed (false breakouts)."""
        if r.total_breakouts == 0:
            return 0.0
        return min(1.0, r.total_false_breakouts / r.total_breakouts)

    @staticmethod
    def _strength_stability(r: MultiBarRunResult) -> float:
        """
        1 - coefficient_of_variation(strength) across final zones.

        High stability (low CV) → zones maintain consistent strength.
        Returns 0 if fewer than 2 zones.
        """
        strengths = [z.strength for z in r.final_zones if z.strength > 0]
        if len(strengths) < 2:
            return 0.0
        mean_s = sum(strengths) / len(strengths)
        if mean_s <= 0:
            return 0.0
        variance = sum((s - mean_s) ** 2 for s in strengths) / len(strengths)
        cv = math.sqrt(variance) / mean_s
        return max(0.0, min(1.0, 1.0 - cv))

    def _coverage(self, r: MultiBarRunResult) -> float:
        """
        Fraction of significant price reversals that had a zone nearby.

        A reversal is a local min/max where price changes direction by
        at least ``reversal_threshold_pct``. A reversal is "covered" if
        any active zone at that bar was within ``coverage_proximity_atr``
        ATR of the reversal price.
        """
        reversals = self._find_reversals(r.close_prices)
        if not reversals:
            return 0.0

        covered = 0
        for rev_idx in reversals:
            if rev_idx >= len(r.bar_zone_snapshots):
                continue
            rev_price = r.close_prices[rev_idx]
            zones_at_bar = r.bar_zone_snapshots[rev_idx]
            if self._any_zone_near(rev_price, zones_at_bar):
                covered += 1

        return min(1.0, covered / len(reversals))

    def _find_reversals(self, prices: List[float]) -> List[int]:
        """
        Find indices of significant price reversals.

        A reversal at index i means price changed direction by at least
        ``reversal_threshold_pct`` relative to the prior swing.
        """
        if len(prices) < 3:
            return []

        reversals: List[int] = []
        threshold = self._reversal_threshold_pct

        # Track swing direction and magnitude
        swing_start = prices[0]
        direction = 0  # 0=unknown, 1=up, -1=down

        for i in range(1, len(prices)):
            pct_change = (prices[i] - swing_start) / swing_start if swing_start != 0 else 0

            if direction == 0:
                # Establish initial direction
                if abs(pct_change) >= threshold:
                    direction = 1 if pct_change > 0 else -1
                continue

            # Check for reversal
            if direction == 1 and pct_change < -threshold:
                # Was going up, now reversed down
                reversals.append(i)
                swing_start = prices[i]
                direction = -1
            elif direction == -1 and pct_change > threshold:
                # Was going down, now reversed up
                reversals.append(i)
                swing_start = prices[i]
                direction = 1
            else:
                # Update swing start if continuing in same direction
                if direction == 1 and prices[i] > swing_start:
                    swing_start = prices[i]
                elif direction == -1 and prices[i] < swing_start:
                    swing_start = prices[i]

        return reversals

    def _any_zone_near(
        self,
        price: float,
        zones: List[dict],
    ) -> bool:
        """Check if any zone is within proximity of the price."""
        for z in zones:
            atr = z.get("atr", 1.0)
            if atr <= 0:
                continue
            proximity = self._coverage_proximity_atr * atr
            if z["lower"] - proximity <= price <= z["upper"] + proximity:
                return True
        return False
