"""Pure immutable runtime-plan compilation for ingestion.

The settings models remain the configuration authority.  This module only
projects validated settings and the resources composed by bootstrap into the
small immutable representation consumed by the runtime supervisor.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import MappingProxyType

from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.settings import IngestionSettings
from libs.common.exceptions import DataIngestionError


@dataclass(frozen=True, slots=True)
class LanePlan:
    """Immutable compiled runtime configuration for one market lane."""

    lane: MarketLane
    live_provider_id: str
    live_symbol: str
    provider_order: tuple[str, ...]
    provider_symbols: Mapping[str, str]
    target_durations: Mapping[str, timedelta]
    base_duration: timedelta
    lookback_duration: timedelta
    history_floor_duration: timedelta

    def __post_init__(self) -> None:
        provider_order = tuple(self.provider_order)
        if not provider_order:
            raise ValueError("provider_order must be non-empty")
        if len(provider_order) != len(set(provider_order)):
            raise ValueError("provider_order must not contain duplicates")

        provider_symbols = dict(self.provider_symbols)
        if self.live_provider_id not in provider_symbols:
            raise ValueError("provider_symbols must include the live provider")
        missing_symbols = set(provider_order) - provider_symbols.keys()
        if missing_symbols:
            raise ValueError(
                "provider_symbols missing provider IDs: "
                + ", ".join(sorted(missing_symbols))
            )

        target_durations = dict(self.target_durations)
        if any(duration <= timedelta(0) for duration in target_durations.values()):
            raise ValueError("target_durations must contain positive durations")
        if self.base_duration <= timedelta(0):
            raise ValueError("base_duration must be positive")
        if self.lookback_duration < self.base_duration or self.lookback_duration < max(
            target_durations.values(),
            default=self.base_duration,
        ):
            raise ValueError("lookback_duration must cover base and target durations")
        if self.history_floor_duration < self.lookback_duration:
            raise ValueError("history_floor_duration must cover lookback_duration")

        object.__setattr__(self, "provider_order", provider_order)
        object.__setattr__(
            self,
            "provider_symbols",
            MappingProxyType(dict(sorted(provider_symbols.items()))),
        )
        object.__setattr__(
            self,
            "target_durations",
            MappingProxyType(
                dict(
                    sorted(
                        target_durations.items(), key=lambda item: (item[1], item[0])
                    )
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class IngestionPlan:
    """Immutable runtime composition compiled from :class:`IngestionSettings`."""

    base_timeframe: str
    alignment_origin: datetime
    reconnect_backoff_seconds: int
    lanes: tuple[LanePlan, ...]
    lanes_by_lane: Mapping[MarketLane, LanePlan] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.reconnect_backoff_seconds < 0:
            raise ValueError("reconnect_backoff_seconds must be non-negative")

        lanes = tuple(self.lanes)
        lane_keys = [
            (
                lane_plan.lane.venue,
                lane_plan.lane.instrument_id,
                lane_plan.lane.timeframe,
            )
            for lane_plan in lanes
        ]
        if lane_keys != sorted(lane_keys):
            raise ValueError("lanes must be deterministically ordered")
        if len(lane_keys) != len(set(lane_keys)):
            raise ValueError("lanes must not contain duplicates")

        object.__setattr__(self, "lanes", lanes)
        object.__setattr__(
            self,
            "lanes_by_lane",
            MappingProxyType({lane_plan.lane: lane_plan for lane_plan in lanes}),
        )


def compile_ingestion_plan(
    settings: IngestionSettings,
    *,
    live_provider_ids: Collection[str],
    historical_provider_ids: Collection[str],
) -> IngestionPlan:
    """Compile settings and composed provider ownership into an immutable plan.

    This function is deliberately free of I/O and runtime objects.  It only
    reads the frozen settings graph and the provider IDs supplied by bootstrap.
    """

    composed_live_provider_ids = frozenset(live_provider_ids)
    owned_historical_provider_ids = frozenset(historical_provider_ids)
    base_timeframe = settings.base_timeframe
    base_duration = timedelta(
        seconds=settings.timeframes[base_timeframe].duration_seconds
    )

    if not any(asset.enabled for asset in settings.assets.values()):
        return IngestionPlan(
            base_timeframe=base_timeframe,
            alignment_origin=settings.calendar.alignment_origin,
            reconnect_backoff_seconds=settings.runtime.reconnect_backoff_seconds,
            lanes=(),
        )

    lane_plans: list[LanePlan] = []
    seen_lanes: set[MarketLane] = set()
    for asset_name in sorted(settings.assets):
        asset = settings.assets[asset_name]
        if not asset.enabled:
            continue
        for instrument_id in sorted(asset.instruments):
            instrument = asset.instruments[instrument_id]
            if instrument.live_provider not in composed_live_provider_ids:
                raise DataIngestionError(
                    f"instrument '{instrument_id}' live provider "
                    f"'{instrument.live_provider}' is not owned by the composed "
                    "live providers"
                )
            if not instrument.historical_providers:
                raise DataIngestionError(
                    f"instrument '{instrument_id}' has no historical providers"
                )
            missing_historical = set(instrument.historical_providers) - (
                owned_historical_provider_ids
            )
            if missing_historical:
                raise DataIngestionError(
                    f"instrument '{instrument_id}' historical providers are not "
                    "owned by the application: " + ", ".join(sorted(missing_historical))
                )

            lane = MarketLane(
                instrument.venue,
                instrument_id,
                base_timeframe,
            )
            if lane in seen_lanes:
                raise DataIngestionError(f"duplicate enabled runtime lane: {lane}")
            seen_lanes.add(lane)

            provider_symbols = dict(instrument.provider_symbols)
            target_durations = {
                timeframe: timedelta(
                    seconds=settings.timeframes[timeframe].duration_seconds
                )
                for timeframe in instrument.timeframes
                if timeframe != base_timeframe
            }
            lookback_duration = max(
                (base_duration, *target_durations.values()),
            )
            configured_history_duration = (
                timedelta(days=settings.recovery.startup_history_days)
                if settings.recovery.startup_history_days is not None
                else timedelta(0)
            )
            lane_plans.append(
                LanePlan(
                    lane=lane,
                    live_provider_id=instrument.live_provider,
                    live_symbol=provider_symbols[instrument.live_provider],
                    provider_order=instrument.historical_providers,
                    provider_symbols=provider_symbols,
                    target_durations=target_durations,
                    base_duration=base_duration,
                    lookback_duration=lookback_duration,
                    history_floor_duration=max(
                        lookback_duration,
                        configured_history_duration,
                    ),
                )
            )

    lane_plans.sort(
        key=lambda lane_plan: (
            lane_plan.lane.venue,
            lane_plan.lane.instrument_id,
            lane_plan.lane.timeframe,
        )
    )
    return IngestionPlan(
        base_timeframe=base_timeframe,
        alignment_origin=settings.calendar.alignment_origin,
        reconnect_backoff_seconds=settings.runtime.reconnect_backoff_seconds,
        lanes=tuple(lane_plans),
    )


__all__ = ["IngestionPlan", "LanePlan", "compile_ingestion_plan"]
