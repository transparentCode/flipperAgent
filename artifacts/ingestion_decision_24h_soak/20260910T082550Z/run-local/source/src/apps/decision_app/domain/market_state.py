"""Offline causal market-state primitives for ``decision_app`` D3.

This module is deliberately infrastructure-free.  It stores only canonical
closed bars and exposes deterministic fixed-duration geometry for the later
readiness and view layers.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING

from libs.contracts.decision import CausalBarView, FrozenMapping, require_utc

if TYPE_CHECKING:
    from apps.decision_app.planning.planner import ResolvedDecisionPlan


class MarketStateError(ValueError):
    """Base error for invalid offline market-state input."""


class TimeframeGeometryError(MarketStateError):
    """Raised when fixed-duration timeframe geometry is invalid or unknown."""


class BarStoreError(MarketStateError):
    """Base error for invalid canonical BarStore operations."""


class BarConflictError(BarStoreError):
    """Raised when one canonical interval is supplied with different values."""


class BarOrderError(BarStoreError):
    """Raised when a canonical series would move backward or overlap."""


class AppendResult(str, Enum):
    """Result of a canonical append operation."""

    INSERTED = "INSERTED"
    DUPLICATE = "DUPLICATE"


def _require_non_empty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _require_positive_capacity(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _sorted_series_items(
    values: Mapping[MarketSeriesKey, int],
) -> dict[MarketSeriesKey, int]:
    return dict(
        sorted(
            values.items(),
            key=lambda item: (
                item[0].asset,
                item[0].venue,
                item[0].instrument_id,
                item[0].timeframe,
            ),
        )
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketSeriesKey:
    """Canonical shared-history identity for one asset/timeframe series."""

    asset: str
    venue: str
    instrument_id: str
    timeframe: str

    def __post_init__(self) -> None:
        for field_name in ("asset", "venue", "instrument_id", "timeframe"):
            _require_non_empty(getattr(self, field_name), field_name=field_name)


@dataclass(frozen=True, slots=True, kw_only=True)
class TimeframeGrid:
    """Explicit fixed-duration UTC geometry used by D3."""

    alignment_origin: datetime
    durations: Mapping[str, timedelta]

    def __post_init__(self) -> None:
        require_utc(self.alignment_origin, field_name="alignment_origin")
        if not isinstance(self.durations, Mapping):
            raise TypeError("durations must be a mapping")
        normalized: dict[str, timedelta] = {}
        for timeframe, duration in self.durations.items():
            _require_non_empty(timeframe, field_name="timeframe")
            if not isinstance(duration, timedelta):
                raise TypeError("timeframe durations must be timedeltas")
            if duration <= timedelta(0):
                raise ValueError("timeframe durations must be positive")
            normalized[timeframe] = duration
        if not normalized:
            raise ValueError("durations must not be empty")
        object.__setattr__(self, "durations", FrozenMapping(normalized))

    def duration(self, timeframe: str) -> timedelta:
        """Return explicit duration or fail for an unknown timeframe."""

        _require_non_empty(timeframe, field_name="timeframe")
        try:
            return self.durations[timeframe]
        except KeyError as exc:
            raise TimeframeGeometryError(
                f"unknown timeframe geometry: {timeframe}"
            ) from exc

    def bucket_bounds(
        self, timeframe: str, instant: datetime
    ) -> tuple[datetime, datetime]:
        """Return the aligned bucket containing ``instant``."""

        require_utc(instant, field_name="instant")
        duration = self.duration(timeframe)
        elapsed = instant - self.alignment_origin
        bucket_index = elapsed // duration
        start = self.alignment_origin + bucket_index * duration
        return start, start + duration

    def expected_closed_cutoff(
        self, timeframe: str, market_as_of: datetime
    ) -> datetime:
        """Return the latest canonical bucket end known to be closed."""

        require_utc(market_as_of, field_name="market_as_of")
        start, _ = self.bucket_bounds(timeframe, market_as_of)
        if market_as_of == start:
            return market_as_of
        return start

    def is_boundary(self, timeframe: str, instant: datetime) -> bool:
        """Return whether ``instant`` is an aligned timeframe boundary."""

        require_utc(instant, field_name="instant")
        start, _ = self.bucket_bounds(timeframe, instant)
        return instant == start


class BarStore:
    """Bounded shared store for canonical closed bars only."""

    def __init__(self, capacities: Mapping[MarketSeriesKey, int]) -> None:
        if not isinstance(capacities, Mapping):
            raise TypeError("capacities must be a mapping")
        normalized: dict[MarketSeriesKey, int] = {}
        for key, capacity in capacities.items():
            if not isinstance(key, MarketSeriesKey):
                raise TypeError("BarStore capacities must use MarketSeriesKey keys")
            normalized[key] = _require_positive_capacity(
                capacity,
                field_name=f"capacity for {key}",
            )
        self._capacities = FrozenMapping(_sorted_series_items(normalized))
        self._bars: dict[MarketSeriesKey, deque[CausalBarView]] = {
            key: deque(maxlen=capacity) for key, capacity in normalized.items()
        }

    @property
    def capacities(self) -> Mapping[MarketSeriesKey, int]:
        """Return immutable registered capacities."""

        return self._capacities

    @property
    def series_keys(self) -> tuple[MarketSeriesKey, ...]:
        """Return registered series in deterministic order."""

        return tuple(self._capacities)

    def capacity_for(self, key: MarketSeriesKey) -> int:
        """Return a registered series capacity."""

        self._require_key(key)
        return self._capacities[key]

    def append(self, key: MarketSeriesKey, bar: CausalBarView) -> AppendResult:
        """Append one canonical bar, or idempotently accept its latest duplicate."""

        self._require_key(key)
        if not isinstance(bar, CausalBarView):
            raise TypeError("bar must be a CausalBarView")
        if not bar.closed:
            raise BarStoreError("BarStore accepts canonical closed bars only")
        if bar.timeframe != key.timeframe:
            raise BarStoreError("bar timeframe must match MarketSeriesKey timeframe")

        retained = self._bars[key]
        if not retained:
            retained.append(bar)
            return AppendResult.INSERTED

        latest = retained[-1]
        if bar.bar_open_at == latest.bar_open_at:
            if bar == latest:
                return AppendResult.DUPLICATE
            raise BarConflictError(
                f"conflicting canonical bar for {key} at {bar.bar_open_at.isoformat()}"
            )
        if bar.bar_open_at < latest.bar_open_at:
            raise BarOrderError("canonical bars must be appended in forward order")
        if bar.bar_open_at < latest.bar_close_at:
            raise BarOrderError("canonical bars must not overlap")

        retained.append(bar)
        return AppendResult.INSERTED

    def append_many(
        self,
        key: MarketSeriesKey,
        bars: Iterable[CausalBarView],
    ) -> tuple[AppendResult, ...]:
        """Append a sequence using the same deterministic single-series rules."""

        return tuple(self.append(key, bar) for bar in bars)

    def bars_at(
        self,
        key: MarketSeriesKey,
        as_of: datetime,
        limit: int | None = None,
    ) -> tuple[CausalBarView, ...]:
        """Return retained canonical bars whose close is at or before ``as_of``."""

        self._require_key(key)
        require_utc(as_of, field_name="as_of")
        if limit is not None:
            _require_positive_capacity(limit, field_name="limit")
        bars = tuple(bar for bar in self._bars[key] if bar.market_as_of <= as_of)
        return bars if limit is None else bars[-limit:]

    def latest_at_or_before(
        self,
        key: MarketSeriesKey,
        as_of: datetime,
    ) -> CausalBarView | None:
        """Return the latest retained canonical bar at or before ``as_of``."""

        bars = self.bars_at(key, as_of)
        return bars[-1] if bars else None

    def latest_cutoff(self, key: MarketSeriesKey) -> datetime | None:
        """Return the latest retained canonical close, if any."""

        self._require_key(key)
        return self._bars[key][-1].market_as_of if self._bars[key] else None

    def retained_count(
        self,
        key: MarketSeriesKey,
        as_of: datetime | None = None,
    ) -> int:
        """Return retained count, optionally limited to a causal cutoff."""

        self._require_key(key)
        if as_of is None:
            return len(self._bars[key])
        return len(self.bars_at(key, as_of))

    def _require_key(self, key: MarketSeriesKey) -> None:
        if not isinstance(key, MarketSeriesKey):
            raise TypeError("key must be a MarketSeriesKey")
        if key not in self._bars:
            raise KeyError(f"unregistered market series: {key}")


def _validate_projection_geometry(
    trigger_timeframe: str,
    decision_timeframe: str,
    timeframe_grid: TimeframeGrid,
) -> int:
    trigger_duration = timeframe_grid.duration(trigger_timeframe)
    decision_duration = timeframe_grid.duration(decision_timeframe)
    if trigger_duration >= decision_duration:
        raise TimeframeGeometryError(
            "projected decision timeframe requires a shorter trigger timeframe"
        )
    ratio, remainder = divmod(decision_duration, trigger_duration)
    if remainder != timedelta(0):
        raise TimeframeGeometryError(
            "decision timeframe must be an integer multiple of trigger timeframe"
        )
    if ratio <= 0:
        raise TimeframeGeometryError("projection ratio must be positive")
    return ratio


def validate_canonical_bar_geometry(
    key: MarketSeriesKey,
    bar: CausalBarView,
    timeframe_grid: TimeframeGrid,
) -> None:
    """Require one canonical bar to match the configured UTC timeframe grid."""

    if not isinstance(key, MarketSeriesKey):
        raise TypeError("key must be a MarketSeriesKey")
    if not isinstance(bar, CausalBarView):
        raise TypeError("bar must be a CausalBarView")
    if not isinstance(timeframe_grid, TimeframeGrid):
        raise TypeError("timeframe_grid must be a TimeframeGrid")
    if bar.timeframe != key.timeframe:
        raise TimeframeGeometryError(
            f"bar timeframe {bar.timeframe} does not match series {key.timeframe}"
        )
    duration = timeframe_grid.duration(key.timeframe)
    if bar.bar_close_at - bar.bar_open_at != duration:
        raise TimeframeGeometryError(
            f"canonical {key.timeframe} bar duration does not match timeframe grid"
        )
    bucket_start, bucket_end = timeframe_grid.bucket_bounds(
        key.timeframe,
        bar.bar_open_at,
    )
    if bar.bar_open_at != bucket_start or bar.bar_close_at != bucket_end:
        raise TimeframeGeometryError(
            f"canonical {key.timeframe} bar is not aligned to timeframe grid"
        )


def compile_bar_store_capacities(
    plan: ResolvedDecisionPlan,
    timeframe_grid: TimeframeGrid,
) -> FrozenMapping[MarketSeriesKey, int]:
    """Compile maximum shared retained capacity required by every lane."""

    from apps.decision_app.planning.planner import ResolvedDecisionPlan

    if not isinstance(plan, ResolvedDecisionPlan):
        raise TypeError("plan must be a ResolvedDecisionPlan")
    if not isinstance(timeframe_grid, TimeframeGrid):
        raise TypeError("timeframe_grid must be a TimeframeGrid")

    capacities: dict[MarketSeriesKey, int] = {}
    for lane in plan.lanes:
        decision_key = MarketSeriesKey(
            asset=lane.asset,
            venue=lane.venue,
            instrument_id=lane.instrument_id,
            timeframe=lane.decision_timeframe,
        )
        trigger_key = MarketSeriesKey(
            asset=lane.asset,
            venue=lane.venue,
            instrument_id=lane.instrument_id,
            timeframe=lane.trigger_timeframe,
        )
        required: dict[MarketSeriesKey, int] = {
            decision_key: 1,
            trigger_key: 1,
        }
        timeframe_grid.duration(lane.decision_timeframe)
        timeframe_grid.duration(lane.trigger_timeframe)

        if lane.trigger_timeframe != lane.decision_timeframe:
            ratio = _validate_projection_geometry(
                lane.trigger_timeframe,
                lane.decision_timeframe,
                timeframe_grid,
            )
            required[trigger_key] = max(required[trigger_key], ratio)

        for binding in lane.bindings.values():
            for (
                timeframe,
                bars,
            ) in binding.model_spec.warmup_requirements.bars_by_timeframe.items():
                if bars == 0:
                    continue
                timeframe_grid.duration(timeframe)
                warmup_key = MarketSeriesKey(
                    asset=lane.asset,
                    venue=lane.venue,
                    instrument_id=lane.instrument_id,
                    timeframe=timeframe,
                )
                required[warmup_key] = max(required.get(warmup_key, 0), bars)

        for key, capacity in required.items():
            capacities[key] = max(capacities.get(key, 0), capacity)

    return FrozenMapping(_sorted_series_items(capacities))


__all__ = [
    "AppendResult",
    "BarConflictError",
    "BarOrderError",
    "BarStore",
    "BarStoreError",
    "MarketSeriesKey",
    "MarketStateError",
    "TimeframeGeometryError",
    "TimeframeGrid",
    "compile_bar_store_capacities",
    "validate_canonical_bar_geometry",
]
