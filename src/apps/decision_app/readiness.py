"""Pure lane market-readiness evaluation for the D3 offline data core."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

from apps.decision_app.contracts import (
    InputReadCursor,
    LaneCommitWatermark,
    LaneReadiness,
)
from apps.decision_app.market_state import (
    BarStore,
    MarketSeriesKey,
    TimeframeGrid,
    _validate_projection_geometry,
    validate_canonical_bar_geometry,
)
from apps.decision_app.planner import ResolvedLanePlan
from libs.contracts.decision import CausalBarView, FrozenMapping, require_utc


def _require_non_empty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
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
class LaneMarketRequirements:
    """Minimum retained canonical history required by one resolved lane."""

    lane_id: str
    minimum_bars_by_series: Mapping[MarketSeriesKey, int]
    decision_series: MarketSeriesKey
    trigger_series: MarketSeriesKey
    projected_decision: bool

    def __post_init__(self) -> None:
        _require_non_empty(self.lane_id, field_name="lane_id")
        if not isinstance(self.decision_series, MarketSeriesKey):
            raise TypeError("decision_series must be a MarketSeriesKey")
        if not isinstance(self.trigger_series, MarketSeriesKey):
            raise TypeError("trigger_series must be a MarketSeriesKey")
        if not isinstance(self.projected_decision, bool):
            raise TypeError("projected_decision must be a bool")
        if not isinstance(self.minimum_bars_by_series, Mapping):
            raise TypeError("minimum_bars_by_series must be a mapping")
        normalized: dict[MarketSeriesKey, int] = {}
        for key, count in self.minimum_bars_by_series.items():
            if not isinstance(key, MarketSeriesKey):
                raise TypeError("minimum_bars_by_series keys must be MarketSeriesKey")
            if isinstance(count, bool) or not isinstance(count, int):
                raise TypeError("minimum retained bars must be integers")
            if count <= 0:
                raise ValueError("minimum retained bars must be positive")
            if key.asset != self.decision_series.asset:
                raise ValueError("all required series must use the lane asset")
            if key.venue != self.decision_series.venue:
                raise ValueError("all required series must use the lane venue")
            if key.instrument_id != self.decision_series.instrument_id:
                raise ValueError("all required series must use the lane instrument_id")
            normalized[key] = count
        if self.decision_series not in normalized:
            raise ValueError("decision_series must be included in requirements")
        if self.trigger_series not in normalized:
            raise ValueError("trigger_series must be included in requirements")
        if self.projected_decision and self.trigger_series == self.decision_series:
            raise ValueError("projected decision requires distinct trigger series")
        object.__setattr__(
            self,
            "minimum_bars_by_series",
            FrozenMapping(_sorted_series_items(normalized)),
        )

    @property
    def required_bars_by_series(self) -> Mapping[MarketSeriesKey, int]:
        """Alias expressing the same minimum-retention contract."""

        return self.minimum_bars_by_series


def compile_lane_market_requirements(
    lane: ResolvedLanePlan,
    timeframe_grid: TimeframeGrid,
) -> LaneMarketRequirements:
    """Compile required shared market series for one resolved lane."""

    if not isinstance(lane, ResolvedLanePlan):
        raise TypeError("lane must be a ResolvedLanePlan")
    if not isinstance(timeframe_grid, TimeframeGrid):
        raise TypeError("timeframe_grid must be a TimeframeGrid")

    decision_series = MarketSeriesKey(
        asset=lane.asset,
        venue=lane.venue,
        instrument_id=lane.instrument_id,
        timeframe=lane.decision_timeframe,
    )
    trigger_series = MarketSeriesKey(
        asset=lane.asset,
        venue=lane.venue,
        instrument_id=lane.instrument_id,
        timeframe=lane.trigger_timeframe,
    )
    required: dict[MarketSeriesKey, int] = {
        decision_series: 1,
        trigger_series: 1,
    }
    timeframe_grid.duration(lane.decision_timeframe)
    timeframe_grid.duration(lane.trigger_timeframe)

    projected = lane.trigger_timeframe != lane.decision_timeframe
    if projected:
        _validate_projection_geometry(
            lane.trigger_timeframe,
            lane.decision_timeframe,
            timeframe_grid,
        )

    for binding in lane.bindings.values():
        for (
            timeframe,
            bars,
        ) in binding.model_spec.warmup_requirements.bars_by_timeframe.items():
            if bars == 0:
                continue
            timeframe_grid.duration(timeframe)
            key = MarketSeriesKey(
                asset=lane.asset,
                venue=lane.venue,
                instrument_id=lane.instrument_id,
                timeframe=timeframe,
            )
            required[key] = max(required.get(key, 0), bars)

    return LaneMarketRequirements(
        lane_id=lane.lane_id,
        minimum_bars_by_series=_sorted_series_items(required),
        decision_series=decision_series,
        trigger_series=trigger_series,
        projected_decision=projected,
    )


def validate_lane_market_requirements(
    resolved_lane: ResolvedLanePlan,
    requirements: LaneMarketRequirements,
    timeframe_grid: TimeframeGrid,
) -> LaneMarketRequirements:
    """Ensure supplied requirements are exactly the lane/grid-derived contract."""

    if not isinstance(resolved_lane, ResolvedLanePlan):
        raise TypeError("resolved_lane must be a ResolvedLanePlan")
    if not isinstance(requirements, LaneMarketRequirements):
        raise TypeError("requirements must be LaneMarketRequirements")
    canonical = compile_lane_market_requirements(resolved_lane, timeframe_grid)
    if requirements.lane_id != canonical.lane_id:
        raise ValueError("requirements lane_id must match resolved lane")
    if requirements.decision_series != canonical.decision_series:
        raise ValueError("requirements decision_series must match resolved lane")
    if requirements.trigger_series != canonical.trigger_series:
        raise ValueError("requirements trigger_series must match resolved lane")
    if requirements.projected_decision != canonical.projected_decision:
        raise ValueError("requirements projected_decision must match resolved lane")
    if dict(requirements.minimum_bars_by_series) != dict(
        canonical.minimum_bars_by_series
    ):
        raise ValueError(
            "requirements minimum_bars_by_series must match resolved lane warmup"
        )
    return requirements


def compile_lane_causal_history_requirements(
    lane: ResolvedLanePlan,
    feature_plan: object,
    timeframe_grid: TimeframeGrid,
) -> Mapping[MarketSeriesKey, int]:
    """Merge D3 lane demand and D4 feature lookback demand by maximum."""

    from apps.decision_app.features import FeaturePlan

    if not isinstance(feature_plan, FeaturePlan):
        raise TypeError("feature_plan must be a FeaturePlan")
    if feature_plan.lane_id != lane.lane_id:
        raise ValueError("feature_plan lane_id must match resolved lane")
    if feature_plan.base_lane_revision != lane.effective_lane_revision:
        raise ValueError("feature_plan revision must match resolved lane")
    merged = dict(
        compile_lane_market_requirements(
            lane,
            timeframe_grid,
        ).minimum_bars_by_series
    )
    for history in feature_plan.history_requirements.values():
        for key, count in history.items():
            merged[key] = max(merged.get(key, 0), count)
    return FrozenMapping(_sorted_series_items(merged))


def _is_contiguous_recent_window(
    bars: tuple[CausalBarView, ...],
    *,
    required_count: int,
    expected_cutoff: datetime,
) -> bool:
    """Check the required recent sequence under continuous UTC semantics."""

    if required_count == 0:
        return True
    if len(bars) < required_count:
        return False
    window = bars[-required_count:]
    if window[-1].market_as_of != expected_cutoff:
        return False
    return all(
        current.bar_open_at == previous.bar_close_at
        for previous, current in pairwise(window)
    )


def _projection_source_bars(
    bar_store: BarStore,
    trigger_series: MarketSeriesKey,
    decision_timeframe: str,
    timeframe_grid: TimeframeGrid,
    market_as_of: datetime,
) -> tuple[CausalBarView, ...] | None:
    """Return complete trigger bars for an open decision bucket, if present."""

    bucket_start, bucket_end = timeframe_grid.bucket_bounds(
        decision_timeframe,
        market_as_of,
    )
    if not bucket_start < market_as_of < bucket_end:
        return None

    trigger_duration = timeframe_grid.duration(trigger_series.timeframe)
    elapsed = market_as_of - bucket_start
    expected_count, remainder = divmod(elapsed, trigger_duration)
    if remainder != timedelta(0) or expected_count <= 0:
        return None

    candidates = tuple(
        bar
        for bar in bar_store.bars_at(trigger_series, market_as_of)
        if bar.bar_open_at >= bucket_start and bar.bar_close_at <= market_as_of
    )
    if len(candidates) != expected_count:
        return None
    for bar in candidates:
        validate_canonical_bar_geometry(trigger_series, bar, timeframe_grid)
    if not candidates or candidates[0].bar_open_at != bucket_start:
        return None
    if candidates[-1].bar_close_at != market_as_of:
        return None
    previous_close = bucket_start
    for bar in candidates:
        if bar.bar_open_at != previous_close:
            return None
        if bar.bar_close_at - bar.bar_open_at != trigger_duration:
            return None
        previous_close = bar.bar_close_at
    return candidates


class LaneReadinessEvaluator:
    """Pure evaluator for canonical lane market-state readiness."""

    @staticmethod
    def evaluate(
        resolved_lane: ResolvedLanePlan,
        requirements: LaneMarketRequirements,
        bar_store: BarStore,
        timeframe_grid: TimeframeGrid,
        market_as_of: datetime,
        input_read_cursor: InputReadCursor,
        lane_commit_watermark: LaneCommitWatermark,
    ) -> LaneReadiness:
        if not isinstance(resolved_lane, ResolvedLanePlan):
            raise TypeError("resolved_lane must be a ResolvedLanePlan")
        if not isinstance(requirements, LaneMarketRequirements):
            raise TypeError("requirements must be LaneMarketRequirements")
        if not isinstance(bar_store, BarStore):
            raise TypeError("bar_store must be a BarStore")
        if not isinstance(timeframe_grid, TimeframeGrid):
            raise TypeError("timeframe_grid must be a TimeframeGrid")
        if not isinstance(input_read_cursor, InputReadCursor):
            raise TypeError("input_read_cursor must be an InputReadCursor")
        if not isinstance(lane_commit_watermark, LaneCommitWatermark):
            raise TypeError("lane_commit_watermark must be a LaneCommitWatermark")
        if lane_commit_watermark.lane_id != resolved_lane.lane_id:
            raise ValueError("lane_commit_watermark lane_id must match resolved lane")
        require_utc(market_as_of, field_name="market_as_of")
        validate_lane_market_requirements(
            resolved_lane,
            requirements,
            timeframe_grid,
        )

        required_cutoff = timeframe_grid.expected_closed_cutoff(
            resolved_lane.decision_timeframe,
            market_as_of,
        )
        observed_cutoffs: dict[str, datetime] = {}
        warming: list[str] = []
        degraded: list[str] = []
        histories: dict[MarketSeriesKey, tuple[CausalBarView, ...]] = {}

        for key, minimum_count in requirements.minimum_bars_by_series.items():
            expected_cutoff = timeframe_grid.expected_closed_cutoff(
                key.timeframe,
                market_as_of,
            )
            history = bar_store.bars_at(key, expected_cutoff)
            histories[key] = history
            for bar in history:
                validate_canonical_bar_geometry(key, bar, timeframe_grid)
            count = len(history)
            latest = history[-1] if history else None
            if latest is not None:
                observed_cutoffs[key.timeframe] = max(
                    observed_cutoffs.get(key.timeframe, latest.market_as_of),
                    latest.market_as_of,
                )
            if count < minimum_count:
                warming.append(f"{key.timeframe}:history")
                continue
            if latest is None or latest.market_as_of != expected_cutoff:
                degraded.append(f"{key.timeframe}:cutoff")
            elif not _is_contiguous_recent_window(
                history,
                required_count=minimum_count,
                expected_cutoff=expected_cutoff,
            ):
                degraded.append(f"{key.timeframe}:history_gap")

        if not requirements.projected_decision and not timeframe_grid.is_boundary(
            resolved_lane.decision_timeframe,
            market_as_of,
        ):
            degraded.append(f"{resolved_lane.decision_timeframe}:boundary")

        if requirements.projected_decision and timeframe_grid.is_boundary(
            resolved_lane.decision_timeframe,
            market_as_of,
        ):
            decision_bar = bar_store.latest_at_or_before(
                requirements.decision_series,
                market_as_of,
            )
            if decision_bar is None or decision_bar.market_as_of != market_as_of:
                decision_history = histories[requirements.decision_series]
                decision_minimum = requirements.minimum_bars_by_series[
                    requirements.decision_series
                ]
                decision_duration = timeframe_grid.duration(
                    requirements.decision_series.timeframe
                )
                previous_cutoff = market_as_of - decision_duration
                prior_history = tuple(
                    bar
                    for bar in decision_history
                    if bar.market_as_of <= previous_cutoff
                )
                prior_window_complete = _is_contiguous_recent_window(
                    prior_history,
                    required_count=max(0, decision_minimum - 1),
                    expected_cutoff=previous_cutoff,
                )
                if (
                    len(prior_history) == max(0, decision_minimum - 1)
                    and prior_window_complete
                ):
                    warming = [
                        item
                        for item in warming
                        if item != f"{requirements.decision_series.timeframe}:history"
                    ]
                    degraded.append(f"{resolved_lane.decision_timeframe}:cutoff")

        if (
            requirements.projected_decision
            and not timeframe_grid.is_boundary(
                resolved_lane.decision_timeframe,
                market_as_of,
            )
            and not warming
            and _projection_source_bars(
                bar_store,
                requirements.trigger_series,
                resolved_lane.decision_timeframe,
                timeframe_grid,
                market_as_of,
            )
            is None
        ):
            degraded.append(f"{requirements.trigger_series.timeframe}:projection")

        missing = tuple(sorted(set(warming + degraded)))
        if warming:
            state = "WARMING"
        elif degraded:
            state = "DEGRADED"
        else:
            state = "LIVE"
        return LaneReadiness(
            state=state,  # type: ignore[arg-type]
            required_cutoff=required_cutoff,
            input_read_cursor=input_read_cursor,
            observed_cutoffs=observed_cutoffs,
            lane_commit_watermark=lane_commit_watermark,
            missing_inputs=missing,
            missing_dependencies=(),
            last_rewarm_reason=None,
        )


__all__ = [
    "LaneMarketRequirements",
    "LaneReadinessEvaluator",
    "compile_lane_causal_history_requirements",
    "compile_lane_market_requirements",
    "validate_lane_market_requirements",
]
