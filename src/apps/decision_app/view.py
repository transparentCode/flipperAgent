"""Immutable direct and projected lane market views for D3."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from itertools import pairwise

from apps.decision_app.contracts import (
    InputReadCursor,
    LaneCommitWatermark,
)
from apps.decision_app.market_state import BarStore, MarketSeriesKey, TimeframeGrid
from apps.decision_app.planner import ResolvedLanePlan
from apps.decision_app.readiness import (
    LaneMarketRequirements,
    LaneReadinessEvaluator,
    _projection_source_bars,
)
from libs.contracts.decision import (
    CausalBarView,
    FrozenMapping,
    deep_freeze,
    require_utc,
)


def _require_non_empty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _freeze_semantic_mapping(
    value: Mapping[str, object], *, field_name: str
) -> FrozenMapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    return FrozenMapping(
        {key: deep_freeze(item) for key, item in sorted(value.items())}
    )


def _normalize_causal_views(
    value: Mapping[str, Sequence[CausalBarView]],
    market_as_of: datetime,
) -> FrozenMapping[str, tuple[CausalBarView, ...]]:
    if not isinstance(value, Mapping):
        raise TypeError("causal_bar_views must be a mapping")
    normalized: dict[str, tuple[CausalBarView, ...]] = {}
    for timeframe, bars in sorted(value.items()):
        _require_non_empty(timeframe, field_name="causal_bar_views timeframe")
        if isinstance(bars, (str, bytes)) or not isinstance(bars, Sequence):
            raise TypeError("causal_bar_views values must be bar sequences")
        sequence = tuple(bars)
        if any(not isinstance(bar, CausalBarView) for bar in sequence):
            raise TypeError("causal_bar_views must contain CausalBarView values")
        if any(not bar.closed for bar in sequence):
            raise ValueError("causal_bar_views may contain canonical closed bars only")
        if any(bar.timeframe != timeframe for bar in sequence):
            raise ValueError("causal bar timeframe must match its mapping key")
        for bar in sequence:
            if bar.market_as_of > market_as_of:
                raise ValueError("causal bar market_as_of cannot be after view cutoff")
        for previous, current in pairwise(sequence):
            if current.bar_open_at <= previous.bar_open_at:
                raise ValueError("causal bars must be chronologically ordered")
            if current.bar_open_at < previous.bar_close_at:
                raise ValueError("causal bars must not overlap")
        normalized[timeframe] = sequence
    return FrozenMapping(normalized)


def _normalize_observed_cutoffs(
    value: Mapping[str, datetime],
    causal_views: Mapping[str, Sequence[CausalBarView]],
    market_as_of: datetime,
) -> FrozenMapping[str, datetime]:
    if not isinstance(value, Mapping):
        raise TypeError("observed_cutoffs must be a mapping")
    normalized: dict[str, datetime] = {}
    for timeframe, cutoff in value.items():
        _require_non_empty(timeframe, field_name="observed_cutoffs timeframe")
        require_utc(cutoff, field_name="observed_cutoff")
        if cutoff > market_as_of:
            raise ValueError("observed cutoff cannot be after view market_as_of")
        bars = causal_views.get(timeframe, ())
        if not bars:
            raise ValueError(
                f"observed cutoff {timeframe} has no available causal view"
            )
        if cutoff > bars[-1].market_as_of:
            raise ValueError("observed cutoff cannot exceed available causal view")
        normalized[timeframe] = cutoff
    return FrozenMapping(dict(sorted(normalized.items())))


@dataclass(frozen=True, slots=True, kw_only=True)
class LaneMarketView:
    """Immutable lane-level causal market input before model context assembly."""

    lane_id: str
    asset: str
    venue: str
    instrument_id: str
    market_as_of: datetime
    decision_timeframe: str
    trigger_timeframe: str
    trigger_mode: str
    decision_bar: CausalBarView
    decision_bar_closed: bool
    causal_bar_views: Mapping[str, Sequence[CausalBarView]] = field(
        default_factory=dict
    )
    observed_cutoffs: Mapping[str, datetime] = field(default_factory=dict)
    provenance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "lane_id",
            "asset",
            "venue",
            "instrument_id",
            "decision_timeframe",
            "trigger_timeframe",
            "trigger_mode",
        ):
            _require_non_empty(getattr(self, field_name), field_name=field_name)
        require_utc(self.market_as_of, field_name="market_as_of")
        if not isinstance(self.decision_bar_closed, bool):
            raise TypeError("decision_bar_closed must be a bool")
        if not isinstance(self.decision_bar, CausalBarView):
            raise TypeError("decision_bar must be a CausalBarView")
        if self.decision_bar.timeframe != self.decision_timeframe:
            raise ValueError("decision_bar timeframe must match decision_timeframe")
        if self.decision_bar.market_as_of != self.market_as_of:
            raise ValueError("decision_bar market_as_of must match view market_as_of")
        if self.decision_bar.closed != self.decision_bar_closed:
            raise ValueError("decision_bar_closed must match decision_bar.closed")
        causal_views = _normalize_causal_views(
            self.causal_bar_views,
            self.market_as_of,
        )
        object.__setattr__(self, "causal_bar_views", causal_views)
        object.__setattr__(
            self,
            "observed_cutoffs",
            _normalize_observed_cutoffs(
                self.observed_cutoffs,
                causal_views,
                self.market_as_of,
            ),
        )
        object.__setattr__(
            self,
            "provenance",
            _freeze_semantic_mapping(self.provenance, field_name="provenance"),
        )


class MarketViewNotReadyError(ValueError):
    """Raised when a view is requested before its causal market state is ready."""

    def __init__(self, readiness: object) -> None:
        self.readiness = readiness
        state = getattr(readiness, "state", "UNKNOWN")
        missing = getattr(readiness, "missing_inputs", ())
        super().__init__(f"lane market view is {state}; missing inputs={missing}")


class DecisionViewBuilder:
    """Build canonical or ephemeral projected views without mutating BarStore."""

    def __init__(self, bar_store: BarStore, timeframe_grid: TimeframeGrid) -> None:
        if not isinstance(bar_store, BarStore):
            raise TypeError("bar_store must be a BarStore")
        if not isinstance(timeframe_grid, TimeframeGrid):
            raise TypeError("timeframe_grid must be a TimeframeGrid")
        self._bar_store = bar_store
        self._timeframe_grid = timeframe_grid

    def build(
        self,
        resolved_lane: ResolvedLanePlan,
        requirements: LaneMarketRequirements,
        market_as_of: datetime,
        *,
        input_read_cursor: InputReadCursor | None = None,
        lane_commit_watermark: LaneCommitWatermark | None = None,
    ) -> LaneMarketView:
        """Build a ready lane view at one explicit causal cutoff."""

        if not isinstance(resolved_lane, ResolvedLanePlan):
            raise TypeError("resolved_lane must be a ResolvedLanePlan")
        if not isinstance(requirements, LaneMarketRequirements):
            raise TypeError("requirements must be LaneMarketRequirements")
        require_utc(market_as_of, field_name="market_as_of")
        if input_read_cursor is None:
            input_read_cursor = InputReadCursor(
                stream_key=f"offline:{resolved_lane.lane_id}",
                latest_market_as_of=market_as_of,
            )
        if lane_commit_watermark is None:
            lane_commit_watermark = LaneCommitWatermark(
                lane_id=resolved_lane.lane_id,
            )
        readiness = LaneReadinessEvaluator.evaluate(
            resolved_lane,
            requirements,
            self._bar_store,
            self._timeframe_grid,
            market_as_of,
            input_read_cursor,
            lane_commit_watermark,
        )
        if readiness.state != "LIVE":
            raise MarketViewNotReadyError(readiness)

        causal_views = self._canonical_views(requirements, market_as_of)
        decision_boundary = self._timeframe_grid.is_boundary(
            resolved_lane.decision_timeframe,
            market_as_of,
        )
        if decision_boundary:
            decision_bar = self._canonical_decision_bar(
                requirements.decision_series,
                market_as_of,
            )
        else:
            source_bars = _projection_source_bars(
                self._bar_store,
                requirements.trigger_series,
                resolved_lane.decision_timeframe,
                self._timeframe_grid,
                market_as_of,
            )
            if source_bars is None:
                raise MarketViewNotReadyError(readiness)
            decision_bar = self._project_decision_bar(
                source_bars,
                resolved_lane.decision_timeframe,
                self._timeframe_grid.bucket_bounds(
                    resolved_lane.decision_timeframe,
                    market_as_of,
                )[1],
                market_as_of,
            )

        observed_cutoffs = {
            timeframe: bars[-1].market_as_of
            for timeframe, bars in causal_views.items()
            if bars
        }
        return LaneMarketView(
            lane_id=resolved_lane.lane_id,
            asset=resolved_lane.asset,
            venue=resolved_lane.venue,
            instrument_id=resolved_lane.instrument_id,
            market_as_of=market_as_of,
            decision_timeframe=resolved_lane.decision_timeframe,
            trigger_timeframe=resolved_lane.trigger_timeframe,
            trigger_mode=resolved_lane.trigger_mode,
            decision_bar=decision_bar,
            decision_bar_closed=decision_bar.closed,
            causal_bar_views=causal_views,
            observed_cutoffs=observed_cutoffs,
            provenance={
                "market_state": "canonical"
                if decision_bar.closed
                else "projected_from_canonical_trigger_bars",
                "decision_bar_market_as_of": decision_bar.market_as_of,
            },
        )

    def build_direct(
        self,
        resolved_lane: ResolvedLanePlan,
        requirements: LaneMarketRequirements,
        market_as_of: datetime,
        *,
        input_read_cursor: InputReadCursor | None = None,
        lane_commit_watermark: LaneCommitWatermark | None = None,
    ) -> LaneMarketView:
        """Explicit alias for callers requesting the canonical path."""

        view = self.build(
            resolved_lane,
            requirements,
            market_as_of,
            input_read_cursor=input_read_cursor,
            lane_commit_watermark=lane_commit_watermark,
        )
        if not view.decision_bar_closed:
            raise ValueError("build_direct requires a canonical closed decision bar")
        return view

    def build_projected(
        self,
        resolved_lane: ResolvedLanePlan,
        requirements: LaneMarketRequirements,
        market_as_of: datetime,
        *,
        input_read_cursor: InputReadCursor | None = None,
        lane_commit_watermark: LaneCommitWatermark | None = None,
    ) -> LaneMarketView:
        """Explicit alias for callers requesting an open-bucket view."""

        view = self.build(
            resolved_lane,
            requirements,
            market_as_of,
            input_read_cursor=input_read_cursor,
            lane_commit_watermark=lane_commit_watermark,
        )
        if view.decision_bar_closed:
            raise ValueError("build_projected requires an open projected decision bar")
        return view

    def _canonical_views(
        self,
        requirements: LaneMarketRequirements,
        market_as_of: datetime,
    ) -> dict[str, tuple[CausalBarView, ...]]:
        views: dict[str, tuple[CausalBarView, ...]] = {}
        for key in requirements.minimum_bars_by_series:
            cutoff = self._timeframe_grid.expected_closed_cutoff(
                key.timeframe,
                market_as_of,
            )
            views[key.timeframe] = self._bar_store.bars_at(
                key,
                cutoff,
                limit=requirements.minimum_bars_by_series[key],
            )
        return dict(sorted(views.items()))

    def _canonical_decision_bar(
        self,
        decision_series: MarketSeriesKey,
        market_as_of: datetime,
    ) -> CausalBarView:
        bar = self._bar_store.latest_at_or_before(decision_series, market_as_of)
        if bar is None or bar.market_as_of != market_as_of:
            raise MarketViewNotReadyError(
                f"missing canonical decision bar at {market_as_of.isoformat()}"
            )
        if not bar.closed:
            raise ValueError("canonical decision bar must be closed")
        return bar

    @staticmethod
    def _project_decision_bar(
        source_bars: Sequence[CausalBarView],
        decision_timeframe: str,
        bucket_end: datetime,
        market_as_of: datetime,
    ) -> CausalBarView:
        if not source_bars:
            raise ValueError("projection requires at least one source bar")
        first = source_bars[0]
        last = source_bars[-1]
        taker_buy_base: Decimal | None
        if any(bar.taker_buy_base is None for bar in source_bars):
            taker_buy_base = None
        else:
            taker_buy_base = sum(
                (bar.taker_buy_base for bar in source_bars),
                Decimal(0),
            )
        return CausalBarView(
            timeframe=decision_timeframe,
            bar_open_at=first.bar_open_at,
            bar_close_at=bucket_end,
            market_as_of=market_as_of,
            open=first.open,
            high=max(bar.high for bar in source_bars),
            low=min(bar.low for bar in source_bars),
            close=last.close,
            volume=sum((bar.volume for bar in source_bars), Decimal(0)),
            taker_buy_base=taker_buy_base,
            closed=False,
        )


__all__ = [
    "DecisionViewBuilder",
    "LaneMarketView",
    "MarketViewNotReadyError",
]
