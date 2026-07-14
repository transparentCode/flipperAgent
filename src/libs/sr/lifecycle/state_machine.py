"""
S/R v2 Lifecycle — Zone State Machine
=======================================
Manages zone lifecycle transitions per the §2D state diagram:

    FORMING → ACTIVE → TESTED → ACTIVE (loop)
                     → BROKEN  → FALSE_BREAKOUT → ACTIVE
                               → FLIPPED
    any → EXPIRED (age / strength floor / pruning)

Every transition is logged as an immutable ``ZoneLifecycleEvent``.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.sr.models import LevelType
from app.sr.models import (
    CandidateLevel,
    LevelFeatureVector,
    ScoredLevel,
    ZoneLifecycleEvent,
    ZoneStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Managed Zone — mutable wrapper around immutable ScoredLevel
# ---------------------------------------------------------------------------

@dataclass
class ManagedZone:
    """
    Mutable zone with lifecycle state.

    Wraps an immutable ``ScoredLevel`` with mutable status,
    strength, and touch history.  Only the ``ZoneLifecycleManager``
    should mutate these fields.
    """

    zone_id: str
    scored_level: ScoredLevel
    status: ZoneStatus = ZoneStatus.FORMING
    strength: float = 0.0
    touch_count: int = 0
    bars_since_formation: int = 0
    bars_since_last_touch: int = 0
    bars_since_break: int = 0
    breakout_direction: Optional[str] = None  # "up" or "down"
    false_breakout_count: int = 0
    events: List[ZoneLifecycleEvent] = field(default_factory=list)
    
    # Merge metadata
    detection_timestamp: Optional[datetime] = None
    reinforcement_timestamp: Optional[datetime] = None
    contributing_kernels: List[str] = field(default_factory=list)
    expired_at_bar: Optional[int] = None  # bar_index when zone transitioned to EXPIRED

    # --- Predictive lifecycle fields ---
    hold_probability: float = 0.5          # Bayesian P(hold) updated on each touch
    resilience: float = 0.0                # False-breakout resilience score [0, 1]
    _touches_held: int = 0                 # touches that bounced (for hold_probability)
    _touches_broken: int = 0               # touches that broke through (for hold_probability)

    @property
    def center_price(self) -> float:
        return self.scored_level.candidate.center_price

    @property
    def lower_bound(self) -> float:
        return self.scored_level.candidate.lower_bound

    @property
    def upper_bound(self) -> float:
        return self.scored_level.candidate.upper_bound

    @property
    def level_type(self) -> LevelType:
        return self.scored_level.candidate.level_type

    @property
    def atr(self) -> float:
        return self.scored_level.candidate.atr_at_detection

    @property
    def kernel_name(self) -> str:
        return self.scored_level.candidate.kernel_name


# ---------------------------------------------------------------------------
# Valid transitions
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS = {
    ZoneStatus.FORMING: {ZoneStatus.ACTIVE, ZoneStatus.EXPIRED},
    ZoneStatus.ACTIVE: {ZoneStatus.TESTED, ZoneStatus.BROKEN, ZoneStatus.EXPIRED},
    ZoneStatus.TESTED: {ZoneStatus.ACTIVE, ZoneStatus.BROKEN, ZoneStatus.EXPIRED},
    ZoneStatus.BROKEN: {ZoneStatus.FALSE_BREAKOUT, ZoneStatus.FLIPPED, ZoneStatus.EXPIRED},
    ZoneStatus.FALSE_BREAKOUT: {ZoneStatus.ACTIVE, ZoneStatus.EXPIRED},
    ZoneStatus.FLIPPED: {ZoneStatus.ACTIVE, ZoneStatus.TESTED, ZoneStatus.BROKEN, ZoneStatus.EXPIRED},
    ZoneStatus.EXPIRED: set(),  # terminal
}


# ---------------------------------------------------------------------------
# Zone Lifecycle Manager
# ---------------------------------------------------------------------------

class ZoneLifecycleManager:
    """
    Manages the lifecycle of all active zones for one (asset, TF) pair.

    Processes bar-by-bar updates, applies transition rules, and emits
    ``ZoneLifecycleEvent`` for every state change (audit trail).

    Configuration comes from the resolved ``LifecycleConfig``.
    """

    def __init__(self, config: Dict[str, Any]):
        self._config = config
        self._zones: Dict[str, ManagedZone] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def active_zones(self) -> List[ManagedZone]:
        """All zones not in EXPIRED state."""
        return [z for z in self._zones.values() if z.status != ZoneStatus.EXPIRED]

    @property
    def all_zones(self) -> List[ManagedZone]:
        return list(self._zones.values())

    def ingest_scored_levels(
        self,
        scored_levels: List[ScoredLevel],
        bar_index: int,
        timestamp: datetime,
    ) -> List[ManagedZone]:
        """
        Register new scored levels as FORMING zones.

        If a level overlaps with an existing zone (same center ± 0.5 ATR),
        it merges with the existing zone instead of discarding.
        Returns newly created zones.
        """
        new_zones: List[ManagedZone] = []
        for sl in scored_levels:
            existing = self._find_duplicate_zone(sl)
            if existing is not None:
                if existing.status == ZoneStatus.EXPIRED:
                    # Suppress re-creation at a recently-expired price.
                    continue
                self._merge_zone(existing, sl, bar_index, timestamp)
                continue

            zone_id = str(uuid.uuid4())[:12]
            zone = ManagedZone(
                zone_id=zone_id,
                scored_level=sl,
                status=ZoneStatus.FORMING,
                strength=sl.strength,
                touch_count=0,
                bars_since_formation=0,
                detection_timestamp=timestamp,
                reinforcement_timestamp=timestamp,
                contributing_kernels=list(sl.contributing_kernels) if sl.contributing_kernels else [sl.candidate.kernel_name],
            )

            # Immediately promote to ACTIVE if kernel agreement clears the configured threshold
            # or raw_score is high enough
            agreement_threshold = self._config.get("auto_promote_kernel_agreement", 2)
            # Cap at number of enabled kernels to avoid impossible thresholds
            enabled_kernels = self._config.get("enabled_kernels", [])
            if enabled_kernels:
                agreement_threshold = min(agreement_threshold, len(enabled_kernels))
            if (sl.features.kernel_agreement >= agreement_threshold
                    or sl.strength >= self._config.get("min_strength", 0.3)):
                self._transition(
                    zone, ZoneStatus.ACTIVE, "auto_promote",
                    bar_index=bar_index, timestamp=timestamp,
                    price=sl.candidate.center_price,
                )
            else:
                self._record_event(
                    zone, ZoneStatus.FORMING, ZoneStatus.FORMING,
                    "created", bar_index, timestamp,
                    sl.candidate.center_price,
                )

            self._zones[zone_id] = zone
            new_zones.append(zone)

        return new_zones

    def update(
        self,
        current_price: float,
        current_volume: float,
        avg_volume: float,
        atr: float,
        bar_index: int,
        timestamp: datetime,
        gap_size_atr: float = 0.0,
        gap_direction: Optional[str] = None,
    ) -> List[ZoneLifecycleEvent]:
        """
        Process one bar for all active zones.

        Returns list of events emitted during this update.
        """
        events: List[ZoneLifecycleEvent] = []

        for zone in list(self._zones.values()):
            if zone.status == ZoneStatus.EXPIRED:
                continue

            zone.bars_since_formation += 1
            zone.bars_since_last_touch += 1

            if zone.status == ZoneStatus.BROKEN:
                zone.bars_since_break += 1

            zone_events = self._process_zone(
                zone, current_price, current_volume, avg_volume,
                atr, bar_index, timestamp, gap_size_atr, gap_direction,
            )
            events.extend(zone_events)

        # Stale zone Garbage Collection
        events.extend(self._gc_stale_zones(current_price, atr, bar_index, timestamp))

        # Prune excess zones
        max_zones = self._config.get("max_active_zones", 10)
        prune_events = self._prune_weakest(max_zones, bar_index, timestamp, current_price)
        events.extend(prune_events)

        # GC expired zones that have been dead long enough to free the price
        # for legitimate re-detection in a future context.
        self._gc_expired_zones(bar_index)

        return events

    def get_zone(self, zone_id: str) -> Optional[ManagedZone]:
        return self._zones.get(zone_id)

    # ------------------------------------------------------------------
    # Per-zone processing
    # ------------------------------------------------------------------

    def _process_zone(
        self,
        zone: ManagedZone,
        price: float,
        volume: float,
        avg_volume: float,
        atr: float,
        bar_index: int,
        timestamp: datetime,
        gap_size_atr: float,
        gap_direction: Optional[str],
    ) -> List[ZoneLifecycleEvent]:
        """Apply all transition rules to one zone. Returns emitted events."""
        events: List[ZoneLifecycleEvent] = []

        # FORMING → ACTIVE (touch or age confirmation)
        if zone.status == ZoneStatus.FORMING:
            if self._is_touching(zone, price, atr):
                zone.touch_count += 1
                zone.bars_since_last_touch = 0
                min_touches = self._config.get("min_touches_to_confirm", 1)
                if zone.touch_count >= min_touches:
                    events.append(self._transition(
                        zone, ZoneStatus.ACTIVE, "touch_confirm",
                        bar_index, timestamp, price, volume,
                    ))
            return events

        # Age decay (continuous)
        age_lambda = self._config.get("age_lambda", 0.002)
        zone.strength *= (1.0 - age_lambda)

        # Inactivity decay — only applied ONCE per threshold crossing,
        # not compounded every bar, to prevent aggressive cascade
        inactivity_threshold = self._config.get("inactivity_threshold", 80)
        inactivity_decay = self._config.get("inactivity_decay", 0.8)
        if zone.bars_since_last_touch == inactivity_threshold:
            zone.strength *= inactivity_decay

        # Strength floor → EXPIRED
        min_strength = self._config.get("min_strength", 0.3)
        if zone.strength < min_strength:
            events.append(self._transition(
                zone, ZoneStatus.EXPIRED, "strength_floor",
                bar_index, timestamp, price, volume,
            ))
            return events

        # Check touch
        if self._is_touching(zone, price, atr):
            zone.touch_count += 1
            zone.bars_since_last_touch = 0

            if zone.status in (ZoneStatus.ACTIVE, ZoneStatus.TESTED):
                # Touch → TESTED
                if zone.status == ZoneStatus.ACTIVE:
                    events.append(self._transition(
                        zone, ZoneStatus.TESTED, "touch",
                        bar_index, timestamp, price, volume,
                    ))
                # Bounce back from TESTED → ACTIVE
                # (stays TESTED until we confirm it held; next bar re-checks)

        # Check breakout
        breakout_dir = self._check_breakout(zone, price, atr, gap_size_atr, gap_direction)
        if breakout_dir and zone.status in (ZoneStatus.ACTIVE, ZoneStatus.TESTED):
            zone.breakout_direction = breakout_dir
            zone.bars_since_break = 0
            # Bayesian hold probability update: touch broken through
            zone._touches_broken += 1
            zone.hold_probability = self._compute_hold_probability(zone)
            events.append(self._transition(
                zone, ZoneStatus.BROKEN, f"breakout_{breakout_dir}",
                bar_index, timestamp, price, volume,
            ))
            return events

        # TESTED → ACTIVE (price moved away = level held)
        if zone.status == ZoneStatus.TESTED:
            if not self._is_in_zone(zone, price, atr):
                # Strength boost for successful test (EMA-smoothed)
                test_boost = self._config.get("test_held_strength_boost", 1.1)
                strength_ema_alpha = self._config.get("strength_ema_alpha", 0.3)
                target = min(1.0, zone.strength * test_boost)
                zone.strength = zone.strength + strength_ema_alpha * (target - zone.strength)
                # Bayesian hold probability update: touch held
                zone._touches_held += 1
                zone.hold_probability = self._compute_hold_probability(zone)
                events.append(self._transition(
                    zone, ZoneStatus.ACTIVE, "test_held",
                    bar_index, timestamp, price, volume,
                ))
                return events

        # BROKEN → FALSE_BREAKOUT or FLIPPED
        if zone.status == ZoneStatus.BROKEN:
            confirm_bars = self._config.get("breakout_confirm_bars", 3)
            false_bk_window = self._config.get("false_breakout_window", 6)

            if zone.bars_since_break <= false_bk_window and self._is_in_zone(zone, price, atr):
                # Price returned inside zone → FALSE_BREAKOUT
                zone.false_breakout_count += 1
                boost = self._config.get("false_breakout_strength_boost", 1.15)
                strength_ema_alpha = self._config.get("strength_ema_alpha", 0.3)
                target = min(1.0, zone.strength * boost)
                zone.strength = zone.strength + strength_ema_alpha * (target - zone.strength)
                zone.bars_since_break = 0
                # Undo the breakout penalty: the touch actually held (liquidity sweep)
                if zone._touches_broken > 0:
                    zone._touches_broken -= 1
                    zone._touches_held += 1
                    zone.hold_probability = self._compute_hold_probability(zone)
                # Update resilience: zone survived a false breakout
                zone.resilience = self._compute_resilience(zone)
                events.append(self._transition(
                    zone, ZoneStatus.FALSE_BREAKOUT, "price_returned",
                    bar_index, timestamp, price, volume,
                ))
                return events
            
            if zone.bars_since_break > confirm_bars:
                # Breakout confirmed — check for polarity flip
                flip_require_retest = self._config.get("flip_require_retest", True)
                max_broken_bars = self._config.get("max_broken_bars", 20)
                if flip_require_retest and self._is_touching(zone, price, atr):
                    # Retest from other side → FLIPPED
                    events.append(self._transition(
                        zone, ZoneStatus.FLIPPED, "polarity_flip",
                        bar_index, timestamp, price, volume,
                    ))
                    return events
                elif not flip_require_retest:
                    events.append(self._transition(
                        zone, ZoneStatus.FLIPPED, "polarity_flip_no_retest",
                        bar_index, timestamp, price, volume,
                    ))
                    return events
                elif zone.bars_since_break > max_broken_bars:
                    # Timeout: zone stuck BROKEN too long → EXPIRED
                    events.append(self._transition(
                        zone, ZoneStatus.EXPIRED, "broken_timeout",
                        bar_index, timestamp, price, volume,
                    ))
                    return events

        # FALSE_BREAKOUT → ACTIVE
        if zone.status == ZoneStatus.FALSE_BREAKOUT:
            zone.bars_since_break += 1
            recovery_bars = self._config.get(
                "false_breakout_recovery_bars",
                self._config.get("false_breakout_window", 6),
            )
            if zone.bars_since_break >= recovery_bars:
                events.append(self._transition(
                    zone, ZoneStatus.ACTIVE, "false_breakout_recovery",
                    bar_index, timestamp, price, volume,
                ))

        return events

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_touching(self, zone: ManagedZone, price: float, atr: float) -> bool:
        """Price is within zone bounds (ATR-adjusted)."""
        touch_proximity = self._config.get("touch_proximity_atr", 0.1)
        touch_tolerance = touch_proximity * atr
        return (zone.lower_bound - touch_tolerance
                <= price
                <= zone.upper_bound + touch_tolerance)

    def _is_in_zone(self, zone: ManagedZone, price: float, atr: float) -> bool:
        """Price is strictly within zone bounds."""
        return zone.lower_bound <= price <= zone.upper_bound

    def _check_breakout(
        self,
        zone: ManagedZone,
        price: float,
        atr: float,
        gap_size_atr: float,
        gap_direction: Optional[str],
    ) -> Optional[str]:
        """
        Check if price has broken through the zone.

        Returns "up" or "down" or None.
        Gap handling respects ``gap_breakout_policy`` from config.
        """
        breakout_atr = self._config.get("breakout_atr_threshold", 0.3)
        threshold = breakout_atr * atr
        breakout_dir: Optional[str] = None

        if zone.level_type == LevelType.RESISTANCE:
            if price > zone.upper_bound + threshold:
                breakout_dir = "up"
        elif zone.level_type == LevelType.SUPPORT:
            if price < zone.lower_bound - threshold:
                breakout_dir = "down"

        if breakout_dir is None:
            return None

        if gap_size_atr > 0 and gap_direction == breakout_dir:
            effective_policy = self._config.get("gap_breakout_policy", "gap_ignored")
            escalation_atr = self._config.get("gap_escalation_atr", 3.0)
            if gap_size_atr > escalation_atr:
                effective_policy = "gap_confirms_break"

            if effective_policy == "gap_suspends_countdown":
                return None

        return breakout_dir

    def _find_duplicate_zone(self, sl: ScoredLevel) -> Optional[ManagedZone]:
        """Check if a scored level is too close to an existing zone and return the closest.

        Includes EXPIRED zones so callers can suppress re-creation at
        recently-expired prices (prevents the create-prune-recreate churn).
        """
        atr = sl.candidate.atr_at_detection
        if atr <= 0:
            atr = 1e-5  # fallback to prevent dedup bypass on zero-ATR
        proximity_atr = self._config.get("dedup_proximity_atr", 0.5)
        best_zone: Optional[ManagedZone] = None
        best_dist = float("inf")
        for zone in self._zones.values():
            dist = abs(zone.center_price - sl.candidate.center_price) / atr
            if dist < proximity_atr and dist < best_dist:
                best_dist = dist
                best_zone = zone
        return best_zone

    def _merge_zone(self, zone: ManagedZone, sl: ScoredLevel, bar_index: int, timestamp: datetime):
        """Reinforce existing zone with incoming duplicate level."""
        zone.reinforcement_timestamp = timestamp
        # Combine strength using configured mode
        mode = self._config.get("merge_strength_mode", "max")
        if mode == "probabilistic_or":
            zone.strength = min(1.0, zone.strength + sl.strength * (1 - zone.strength))
        else:
            # "max" — keep the stronger of the two (no dilution)
            zone.strength = max(zone.strength, sl.strength)
        
        # Union contributing kernels
        incoming_kernels = sl.contributing_kernels if sl.contributing_kernels else [sl.candidate.kernel_name]
        for k in incoming_kernels:
            if k not in zone.contributing_kernels:
                zone.contributing_kernels.append(k)
        
        self._record_event(
            zone, zone.status, zone.status,
            "zone_merged", bar_index, timestamp,
            sl.candidate.center_price,
        )

    def _gc_expired_zones(self, bar_index: int) -> None:
        """Remove expired zones from the dict after max_age_bars since expiration.

        This frees the price level for legitimate re-detection while still
        blocking the rapid create→prune→recreate churn cycle.
        """
        max_age = self._config.get("max_age_bars", 200)
        to_remove = [
            zid for zid, zone in self._zones.items()
            if zone.status == ZoneStatus.EXPIRED
            and zone.expired_at_bar is not None
            and (bar_index - zone.expired_at_bar) > max_age
        ]
        for zid in to_remove:
            del self._zones[zid]

    @staticmethod
    def _compute_hold_probability(zone: ManagedZone) -> float:
        """Bayesian posterior P(hold) using Beta distribution.

        Prior: Beta(1, 1) = uniform.  Each held touch adds to alpha,
        each breakout adds to beta.  Result = alpha / (alpha + beta).
        """
        alpha = 1.0 + zone._touches_held
        beta = 1.0 + zone._touches_broken
        return alpha / (alpha + beta)

    @staticmethod
    def _compute_resilience(zone: ManagedZone) -> float:
        """False-breakout resilience: 1 - exp(-beta * count).

        Zones that survive liquidity sweeps are *stronger*, not weaker.
        Saturates toward 1.0 as false breakout count grows.
        """
        beta = 0.7  # saturation speed — 3 false breakouts ≈ 0.88
        return 1.0 - math.exp(-beta * zone.false_breakout_count)

    def _gc_stale_zones(
        self, price: float, atr: float, bar_index: int, timestamp: datetime,
    ) -> List[ZoneLifecycleEvent]:
        """Purge zones that are too old and far from current price."""
        events: List[ZoneLifecycleEvent] = []
        max_age_bars = self._config.get("max_age_bars", 200)
        stale_distance_atr = self._config.get("stale_distance_atr", 3.0)

        for zone in self.active_zones:
            # Drop if older than max_age_bars without recent touches AND far from price
            if zone.bars_since_last_touch > max_age_bars:
                dist_atr = abs(zone.center_price - price) / max(atr, 1e-5)
                if dist_atr > stale_distance_atr:
                    events.append(self._transition(
                        zone, ZoneStatus.EXPIRED, "stale_zone_gc",
                        bar_index, timestamp, price,
                    ))
        return events

    def _prune_weakest(
        self,
        max_zones: int,
        bar_index: int,
        timestamp: datetime,
        price: float,
    ) -> List[ZoneLifecycleEvent]:
        """Remove weakest zones if count exceeds max, respecting per-kernel minimum."""
        active = self.active_zones
        if len(active) <= max_zones:
            return []

        min_per_kernel = self._config.get("min_zones_per_kernel", 1)

        # Count zones per kernel and protect the minimum quota
        protected: set = set()
        if min_per_kernel > 0:
            from collections import defaultdict
            kernel_zones: Dict[str, List[ManagedZone]] = defaultdict(list)
            for z in active:
                kernel_zones[z.kernel_name].append(z)
            for kernel, zones in kernel_zones.items():
                # Protect the top-N strongest zones per kernel
                zones_sorted = sorted(zones, key=lambda z: z.strength, reverse=True)
                for z in zones_sorted[:min_per_kernel]:
                    protected.add(z.zone_id)

        # Sort by strength ascending — prune weakest, but skip protected
        active.sort(key=lambda z: z.strength)
        to_prune = []
        for zone in active:
            if len(active) - len(to_prune) <= max_zones:
                break
            if zone.zone_id not in protected:
                to_prune.append(zone)

        events = []
        for zone in to_prune:
            events.append(self._transition(
                zone, ZoneStatus.EXPIRED, "max_zones_pruned",
                bar_index, timestamp, price,
            ))
        return events

    def _transition(
        self,
        zone: ManagedZone,
        to_state: ZoneStatus,
        trigger: str,
        bar_index: int,
        timestamp: datetime,
        price: float,
        volume: float = 0.0,
    ) -> ZoneLifecycleEvent:
        """Execute a state transition and emit an event."""
        from_state = zone.status

        if to_state not in _VALID_TRANSITIONS.get(from_state, set()):
            logger.warning(
                "Invalid transition %s → %s for zone %s (trigger: %s) — blocked",
                from_state.name, to_state.name, zone.zone_id, trigger,
            )
            return self._record_event(
                zone, from_state, from_state,
                f"blocked_invalid_{trigger}", bar_index, timestamp, price, volume,
            )

        event = ZoneLifecycleEvent(
            zone_id=zone.zone_id,
            timestamp=timestamp,
            from_state=from_state,
            to_state=to_state,
            trigger=trigger,
            price_at_event=price,
            volume_at_event=volume,
            bar_index=bar_index,
        )

        zone.status = to_state
        if to_state == ZoneStatus.EXPIRED:
            zone.expired_at_bar = bar_index
        zone.events.append(event)
        logger.debug(
            "Zone %s: %s → %s (%s) at price %.2f",
            zone.zone_id, from_state.name, to_state.name, trigger, price,
        )
        return event

    def _record_event(
        self,
        zone: ManagedZone,
        from_state: ZoneStatus,
        to_state: ZoneStatus,
        trigger: str,
        bar_index: int,
        timestamp: datetime,
        price: float,
        volume: float = 0.0,
    ) -> ZoneLifecycleEvent:
        """Record an event without changing state."""
        event = ZoneLifecycleEvent(
            zone_id=zone.zone_id,
            timestamp=timestamp,
            from_state=from_state,
            to_state=to_state,
            trigger=trigger,
            price_at_event=price,
            volume_at_event=volume,
            bar_index=bar_index,
        )
        zone.events.append(event)
        return event
