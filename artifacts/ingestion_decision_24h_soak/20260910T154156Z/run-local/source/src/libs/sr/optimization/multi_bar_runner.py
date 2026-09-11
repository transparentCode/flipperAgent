"""
Multi-Bar Pipeline Runner
==========================
Runs ``SRv2Pipeline.run()`` bar-by-bar across a window of bars,
collecting all ``PipelineResult`` snapshots for quality evaluation.

Used by the per-asset optimizer (Stage 2) to measure zone lifecycle
outcomes over time rather than single-bar snapshot strength.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from app.sr.lifecycle.state_machine import ManagedZone
from app.sr.models import ZoneLifecycleEvent, ZoneStatus
from app.sr.pipeline import PipelineResult, SRv2Pipeline


@dataclass
class MultiBarRunResult:
    """Collected results from running the pipeline bar-by-bar."""

    # Per-bar snapshots (lightweight — only what metrics need)
    bar_count: int = 0
    all_events: List[ZoneLifecycleEvent] = field(default_factory=list)
    final_zones: List[ManagedZone] = field(default_factory=list)

    # Aggregated counters derived during the run
    total_zones_created: int = 0
    total_touches: int = 0
    total_breakouts: int = 0
    total_false_breakouts: int = 0
    zones_reached_active: int = 0
    zones_broken: int = 0
    zones_expired: int = 0

    # Per-bar close prices for coverage analysis
    close_prices: List[float] = field(default_factory=list)

    # Per-bar active zone snapshots (center prices + bounds for coverage)
    bar_zone_snapshots: List[List[Dict[str, float]]] = field(default_factory=list)


class MultiBarRunner:
    """
    Runs an ``SRv2Pipeline`` bar-by-bar and collects lifecycle outcomes.

    The pipeline is stateful — its ``ZoneLifecycleManager`` accumulates
    zones across calls. This runner feeds it one bar at a time and
    records all events emitted.
    """

    def __init__(self, pipeline: SRv2Pipeline):
        self._pipeline = pipeline

    def run(
        self,
        df: pd.DataFrame,
        start_bar: int = 0,
        end_bar: Optional[int] = None,
        progress_callback: Optional[Any] = None,
        max_lookback: int = 2000,
    ) -> MultiBarRunResult:
        """
        Run the pipeline bar-by-bar from ``start_bar`` to ``end_bar``.

        At each step, the pipeline sees a sliding window of at most
        ``max_lookback`` bars ending at the current bar.  This avoids
        O(n²) DataFrame copies that occur when always slicing from bar 0.

        Args:
            df: Full OHLCV DataFrame.
            start_bar: First bar index to process (inclusive).
            end_bar: Last bar index to process (inclusive). Defaults to len(df)-1.
            progress_callback: Optional ``(current, total) -> None`` called
                every bar for progress tracking.
            max_lookback: Maximum historical bars to feed the pipeline per
                step.  Must be >= the largest kernel lookback (default 2000).

        Returns:
            Aggregated run result with all events and zone outcomes.
        """
        if end_bar is None:
            end_bar = len(df) - 1

        result = MultiBarRunResult()
        seen_zone_ids: set = set()
        ever_active_ids: set = set()
        broken_ids: set = set()
        expired_ids: set = set()

        for bar_idx in range(start_bar, end_bar + 1):
            # Progress callback
            if progress_callback is not None:
                progress_callback(bar_idx - start_bar + 1, end_bar - start_bar + 1)

            # Sliding window: cap lookback to avoid O(n²) copies
            win_start = max(0, bar_idx + 1 - max_lookback)
            bar_slice = df.iloc[win_start : bar_idx + 1]
            if len(bar_slice) < 2:
                continue

            pipeline_result = self._pipeline.run(
                bar_slice, bar_index=bar_idx,
            )

            # Collect events
            for event in pipeline_result.events:
                result.all_events.append(event)
                self._classify_event(
                    event, seen_zone_ids, ever_active_ids,
                    broken_ids, expired_ids, result,
                )

            # Track new zones from this bar
            for zone in pipeline_result.new_zones:
                if zone.zone_id not in seen_zone_ids:
                    seen_zone_ids.add(zone.zone_id)
                    result.total_zones_created += 1

            # Record close price for coverage analysis
            result.close_prices.append(float(bar_slice["close"].iloc[-1]))

            # Snapshot active zone positions for coverage
            zone_snap = []
            for z in pipeline_result.active_zones:
                zone_snap.append({
                    "center": z.center_price,
                    "lower": z.lower_bound,
                    "upper": z.upper_bound,
                    "atr": z.atr,
                    "kernel": z.kernel_name,
                    "zone_quality": z.scored_level.zone_quality,
                    "confluence_tier": z.scored_level.confluence_tier,
                    "hold_probability": z.hold_probability,
                    "resilience": z.resilience,
                })
            result.bar_zone_snapshots.append(zone_snap)

        result.bar_count = max(0, end_bar - start_bar + 1)
        result.zones_reached_active = len(ever_active_ids)
        result.zones_broken = len(broken_ids)
        result.zones_expired = len(expired_ids)
        result.final_zones = list(self._pipeline.all_zones)
        return result

    def _classify_event(
        self,
        event: ZoneLifecycleEvent,
        seen_zone_ids: set,
        ever_active_ids: set,
        broken_ids: set,
        expired_ids: set,
        result: MultiBarRunResult,
    ) -> None:
        """Classify a lifecycle event into aggregate counters."""
        trigger = event.trigger

        # Zone reached ACTIVE
        if event.to_state == ZoneStatus.ACTIVE and event.zone_id not in ever_active_ids:
            ever_active_ids.add(event.zone_id)

        # Touch events
        if trigger in ("touch", "touch_confirm"):
            result.total_touches += 1

        # Breakout events
        if trigger.startswith("breakout_"):
            result.total_breakouts += 1
            broken_ids.add(event.zone_id)

        # False breakout (price returned after breakout)
        if trigger == "price_returned":
            result.total_false_breakouts += 1

        # Expired/pruned
        if event.to_state == ZoneStatus.EXPIRED:
            expired_ids.add(event.zone_id)
