"""Leakage-controlled first-touch outcomes and guardrail metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
from statistics import median
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError, SREventType, ZoneSide

from .config import CalibrationConfig
from .contracts import CandidateReplay, SourceCapsule


WINDOW_POLICY = "half_open_utc_daily"


def _finite(value: float, *, field_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractValidationError(f"{field_name} must be finite") from exc
    if not math.isfinite(result):
        raise ContractValidationError(f"{field_name} must be finite")
    return 0.0 if result == 0.0 else result


def _timestamp(value: datetime, *, field_name: str) -> datetime:
    from libs.models.sr.domain.identity import require_utc

    return require_utc(value, field_name=field_name)


@dataclass(frozen=True)
class FirstTouchOutcome:
    zone_id: str
    side: ZoneSide
    first_touch_at: datetime
    touch_bar_id: str
    anchor_close: float
    reference_atr_14: float
    completed: bool
    right_censored: bool
    tenth_outcome_bar_closed_at: datetime | None
    favorable_reference_atr: float | None
    adverse_reference_atr: float | None
    quality_reference_atr: float | None
    invalidated: bool

    def __post_init__(self) -> None:
        if type(self.zone_id) is not str or not self.zone_id:
            raise ContractValidationError("outcome.zone_id must be a non-empty string")
        if type(self.side) is not ZoneSide:
            raise ContractValidationError("outcome.side must be exactly ZoneSide")
        object.__setattr__(self, "first_touch_at", _timestamp(self.first_touch_at, field_name="first_touch_at"))
        if type(self.touch_bar_id) is not str or not self.touch_bar_id:
            raise ContractValidationError("outcome.touch_bar_id must be a non-empty string")
        object.__setattr__(self, "anchor_close", _finite(self.anchor_close, field_name="anchor_close"))
        object.__setattr__(self, "reference_atr_14", _finite(self.reference_atr_14, field_name="reference_atr_14"))
        if self.anchor_close <= 0 or self.reference_atr_14 <= 0:
            raise ContractValidationError("outcome anchor/reference ATR must be positive")
        if type(self.completed) is not bool or type(self.right_censored) is not bool:
            raise ContractValidationError("outcome completion flags must be booleans")
        if self.completed == self.right_censored:
            raise ContractValidationError("outcome must be exactly completed or right-censored")
        tenth = self.tenth_outcome_bar_closed_at
        if tenth is not None:
            tenth = _timestamp(tenth, field_name="tenth_outcome_bar_closed_at")
        object.__setattr__(self, "tenth_outcome_bar_closed_at", tenth)
        values = (self.favorable_reference_atr, self.adverse_reference_atr, self.quality_reference_atr)
        if self.completed:
            if any(value is None for value in values) or tenth is None:
                raise ContractValidationError("completed outcome requires horizon metrics")
            normalized = tuple(_finite(value, field_name="completed outcome metric") for value in values)
            if normalized[0] < 0 or normalized[1] < 0:
                raise ContractValidationError("excursions must be non-negative")
            if abs(normalized[2] - (normalized[0] - normalized[1])) > 1e-12:
                raise ContractValidationError("quality must equal favorable minus adverse")
            object.__setattr__(self, "favorable_reference_atr", normalized[0])
            object.__setattr__(self, "adverse_reference_atr", normalized[1])
            object.__setattr__(self, "quality_reference_atr", normalized[2])
        elif any(value is not None for value in values) or self.invalidated:
            raise ContractValidationError("right-censored outcome cannot contain completed metrics")

    def to_payload(self) -> dict[str, Any]:
        from libs.models.sr.domain.identity import utc_isoformat

        return {
            "zone_id": self.zone_id,
            "side": self.side.value,
            "first_touch_at": utc_isoformat(self.first_touch_at),
            "touch_bar_id": self.touch_bar_id,
            "anchor_close": self.anchor_close,
            "reference_atr_14": self.reference_atr_14,
            "completed": self.completed,
            "right_censored": self.right_censored,
            "tenth_outcome_bar_closed_at": None if self.tenth_outcome_bar_closed_at is None else utc_isoformat(self.tenth_outcome_bar_closed_at),
            "favorable_reference_atr": self.favorable_reference_atr,
            "adverse_reference_atr": self.adverse_reference_atr,
            "quality_reference_atr": self.quality_reference_atr,
            "invalidated": self.invalidated,
        }


@dataclass(frozen=True)
class WindowMetrics:
    name: str
    start: datetime
    end: datetime
    total_first_touch_outcomes: int
    completed_first_touch_outcomes: int
    right_censored_first_touch_outcomes: int
    right_censoring_rate: float | None
    support_completed_count: int
    resistance_completed_count: int
    median_favorable_reference_atr: float | None
    median_adverse_reference_atr: float | None
    median_quality_reference_atr: float | None
    invalidated_completed_outcomes: int
    invalidation_rate: float | None
    created_zone_count: int
    eligible_model_bar_count: int
    zone_creation_density_per_100_bars: float | None
    cohort_terminal_count: int
    churn_rate: float | None
    outcomes: tuple[FirstTouchOutcome, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name:
            raise ContractValidationError("metric window name must be non-empty")
        start = _timestamp(self.start, field_name="metric.start")
        end = _timestamp(self.end, field_name="metric.end")
        if start >= end:
            raise ContractValidationError("metric window must be non-empty")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        counts = (
            "total_first_touch_outcomes",
            "completed_first_touch_outcomes",
            "right_censored_first_touch_outcomes",
            "support_completed_count",
            "resistance_completed_count",
            "invalidated_completed_outcomes",
            "created_zone_count",
            "eligible_model_bar_count",
            "cohort_terminal_count",
        )
        for name in counts:
            value = getattr(self, name)
            if isinstance(value, bool) or type(value) is not int or value < 0:
                raise ContractValidationError(f"{name} must be a non-negative integer")
        if self.completed_first_touch_outcomes + self.right_censored_first_touch_outcomes != self.total_first_touch_outcomes:
            raise ContractValidationError("first-touch outcome counts do not reconcile")
        if self.support_completed_count + self.resistance_completed_count != self.completed_first_touch_outcomes:
            raise ContractValidationError("support/resistance counts do not reconcile")
        if self.invalidated_completed_outcomes > self.completed_first_touch_outcomes:
            raise ContractValidationError("invalidated outcomes exceed completed outcomes")
        for name in (
            "right_censoring_rate",
            "invalidation_rate",
            "zone_creation_density_per_100_bars",
            "churn_rate",
            "median_favorable_reference_atr",
            "median_adverse_reference_atr",
            "median_quality_reference_atr",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _finite(value, field_name=name))
        if type(self.outcomes) is not tuple or any(type(item) is not FirstTouchOutcome for item in self.outcomes):
            raise ContractValidationError("outcomes must contain FirstTouchOutcome values")
        if len(self.outcomes) != self.total_first_touch_outcomes:
            raise ContractValidationError("outcome list does not reconcile")

    @property
    def quality_values(self) -> tuple[float, ...]:
        return tuple(outcome.quality_reference_atr for outcome in self.outcomes if outcome.completed and outcome.quality_reference_atr is not None)

    def to_payload(self, *, include_outcomes: bool = True) -> dict[str, Any]:
        from libs.models.sr.domain.identity import utc_isoformat

        payload: dict[str, Any] = {
            "name": self.name,
            "start": utc_isoformat(self.start),
            "end": utc_isoformat(self.end),
            "total_first_touch_outcomes": self.total_first_touch_outcomes,
            "completed_first_touch_outcomes": self.completed_first_touch_outcomes,
            "right_censored_first_touch_outcomes": self.right_censored_first_touch_outcomes,
            "right_censoring_rate": self.right_censoring_rate,
            "support_completed_count": self.support_completed_count,
            "resistance_completed_count": self.resistance_completed_count,
            "median_favorable_reference_atr": self.median_favorable_reference_atr,
            "median_adverse_reference_atr": self.median_adverse_reference_atr,
            "median_quality_reference_atr": self.median_quality_reference_atr,
            "invalidated_completed_outcomes": self.invalidated_completed_outcomes,
            "invalidation_rate": self.invalidation_rate,
            "created_zone_count": self.created_zone_count,
            "eligible_model_bar_count": self.eligible_model_bar_count,
            "zone_creation_density_per_100_bars": self.zone_creation_density_per_100_bars,
            "cohort_terminal_count": self.cohort_terminal_count,
            "churn_rate": self.churn_rate,
        }
        if include_outcomes:
            payload["outcomes"] = [outcome.to_payload() for outcome in self.outcomes]
        return payload


@dataclass(frozen=True)
class CandidateMetrics:
    period: int
    folds: tuple[WindowMetrics, ...]
    pooled: WindowMetrics

    def __post_init__(self) -> None:
        if isinstance(self.period, bool) or type(self.period) is not int or self.period < 1:
            raise ContractValidationError("candidate period must be a positive integer")
        if type(self.folds) is not tuple or any(type(item) is not WindowMetrics for item in self.folds):
            raise ContractValidationError("candidate folds must contain WindowMetrics")
        if type(self.pooled) is not WindowMetrics:
            raise ContractValidationError("candidate pooled metric must be WindowMetrics")

    def to_payload(self) -> dict[str, Any]:
        return {"period": self.period, "folds": [fold.to_payload() for fold in self.folds], "pooled": self.pooled.to_payload()}


def _event_order(replay: CandidateReplay) -> tuple[dict[str, int], dict[str, list[Any]], dict[str, list[Any]]]:
    snapshot_positions = {reference.snapshot_id: index for index, reference in enumerate(replay.trace.snapshots)}
    events_by_zone: dict[str, list[Any]] = {}
    events_by_snapshot: dict[str, list[Any]] = {}
    for event_index, event in enumerate(replay.trace.events):
        event_order = snapshot_positions[event.snapshot_id] * 1_000_000 + event_index
        events_by_zone.setdefault(event.zone_id, []).append((event_order, event))
        events_by_snapshot.setdefault(event.snapshot_id, []).append((event_order, event))
    observations_by_zone: dict[str, list[Any]] = {}
    for observation in replay.trace.zone_observations:
        observations_by_zone.setdefault(observation.zone_id, []).append(observation)
    return snapshot_positions, events_by_zone, observations_by_zone


def _median_or_none(values: list[float]) -> float | None:
    return None if not values else _finite(median(values), field_name="median")


def compute_window_metrics(
    replay: CandidateReplay,
    capsule: SourceCapsule,
    *,
    config: CalibrationConfig,
    name: str,
    start: datetime,
    end: datetime,
) -> WindowMetrics:
    """Compute one window from the already-complete causal replay trace."""
    if type(replay) is not CandidateReplay or type(capsule) is not SourceCapsule:
        raise ContractValidationError("replay and capsule types are invalid")
    if capsule.stage.value != "development" and name.startswith("202"):
        raise ContractValidationError("development windows require a development capsule")
    start = _timestamp(start, field_name="metric.start")
    end = _timestamp(end, field_name="metric.end")
    if start >= end:
        raise ContractValidationError("metric window must be non-empty")
    bars = capsule.bars
    bar_positions = {bar.bar_id: index for index, bar in enumerate(bars)}
    model_positions = {bar.bar_id: index for index, bar in enumerate(replay.model_bars)}
    reference_atr = {bar.bar_id: replay.reference_atr[index] for index, bar in enumerate(replay.model_bars)}
    snapshot_positions, events_by_zone, observations_by_zone = _event_order(replay)
    outcomes: list[FirstTouchOutcome] = []
    created_in_window: set[str] = set()
    terminal_by_end: set[str] = set()
    for zone_id, zone_events_with_order in events_by_zone.items():
        zone_events = [event for _, event in sorted(zone_events_with_order, key=lambda item: item[0])]
        created = next((event for event in zone_events if event.event_type is SREventType.CREATED), None)
        if created is not None and start <= created.timestamp < end:
            created_in_window.add(zone_id)
        # Scoring windows are half-open: an event at ``end`` belongs to the
        # following window and cannot terminate this window's cohort.
        if any(event.event_type in {SREventType.BREAK_CONFIRMED, SREventType.EXPIRED} and event.timestamp < end for event in zone_events):
            terminal_by_end.add(zone_id)
        observations = observations_by_zone.get(zone_id, [])
        if not observations:
            continue
        first_observation = min(observations, key=lambda item: snapshot_positions[item.snapshot_id])
        touch = next((event for event in zone_events if event.event_type is SREventType.TOUCHED and event.timestamp >= first_observation.visible_from), None)
        if touch is None or not (start <= touch.timestamp < end):
            continue
        if touch.bar_id not in bar_positions or touch.bar_id not in model_positions:
            raise ContractValidationError("first-touch event does not map to an aligned source/model bar")
        touch_index = bar_positions[touch.bar_id]
        if bars[touch_index].closed_at != touch.timestamp:
            raise ContractValidationError("first-touch event timestamp does not match source bar close")
        ref = reference_atr.get(touch.bar_id)
        if ref is None or _finite(ref, field_name="reference_atr_14_at_touch") <= 0:
            raise ContractValidationError("first-touch reference ATR is unavailable")
        anchor = bars[touch_index].close
        start_index = touch_index + config.outcome_start_offset_bars
        end_index = start_index + config.outcome_horizon_bars
        complete = end_index <= len(bars) and all(bars[index].closed_at < end for index in range(start_index, end_index))
        break_events = [event for event in zone_events if event.event_type is SREventType.BREAK_CONFIRMED and touch.timestamp < event.timestamp]
        invalidated = False
        tenth = None
        favorable = adverse = quality = None
        if complete:
            horizon = bars[start_index:end_index]
            tenth = horizon[-1].closed_at
            invalidated = any(event.timestamp <= tenth for event in break_events)
            if first_observation.side is ZoneSide.SUPPORT:
                favorable_raw = max(max(bar.high for bar in horizon) - anchor, 0.0)
                adverse_raw = max(anchor - min(bar.low for bar in horizon), 0.0)
            else:
                favorable_raw = max(anchor - min(bar.low for bar in horizon), 0.0)
                adverse_raw = max(max(bar.high for bar in horizon) - anchor, 0.0)
            favorable = _finite(favorable_raw / ref, field_name="favorable_reference_atr")
            adverse = _finite(adverse_raw / ref, field_name="adverse_reference_atr")
            quality = _finite(favorable - adverse, field_name="quality_reference_atr")
        outcomes.append(
            FirstTouchOutcome(
                zone_id=zone_id,
                side=first_observation.side,
                first_touch_at=touch.timestamp,
                touch_bar_id=touch.bar_id,
                anchor_close=anchor,
                reference_atr_14=ref,
                completed=complete,
                right_censored=not complete,
                tenth_outcome_bar_closed_at=tenth,
                favorable_reference_atr=favorable,
                adverse_reference_atr=adverse,
                quality_reference_atr=quality,
                invalidated=invalidated,
            )
        )
    completed = tuple(outcome for outcome in outcomes if outcome.completed)
    quality_values = [outcome.quality_reference_atr for outcome in completed if outcome.quality_reference_atr is not None]
    favorable_values = [outcome.favorable_reference_atr for outcome in completed if outcome.favorable_reference_atr is not None]
    adverse_values = [outcome.adverse_reference_atr for outcome in completed if outcome.adverse_reference_atr is not None]
    eligible_bars = sum(start <= bar.closed_at < end for bar in replay.model_bars)
    density = None if eligible_bars == 0 else _finite(100.0 * len(created_in_window) / eligible_bars, field_name="zone_creation_density")
    invalidated_count = sum(outcome.invalidated for outcome in completed)
    right_censored = sum(outcome.right_censored for outcome in outcomes)
    return WindowMetrics(
        name=name,
        start=start,
        end=end,
        total_first_touch_outcomes=len(outcomes),
        completed_first_touch_outcomes=len(completed),
        right_censored_first_touch_outcomes=right_censored,
        right_censoring_rate=None if not outcomes else _finite(right_censored / len(outcomes), field_name="right_censoring_rate"),
        support_completed_count=sum(outcome.side is ZoneSide.SUPPORT for outcome in completed),
        resistance_completed_count=sum(outcome.side is ZoneSide.RESISTANCE for outcome in completed),
        median_favorable_reference_atr=_median_or_none(favorable_values),
        median_adverse_reference_atr=_median_or_none(adverse_values),
        median_quality_reference_atr=_median_or_none(quality_values),
        invalidated_completed_outcomes=invalidated_count,
        invalidation_rate=None if not completed else _finite(invalidated_count / len(completed), field_name="invalidation_rate"),
        created_zone_count=len(created_in_window),
        eligible_model_bar_count=eligible_bars,
        zone_creation_density_per_100_bars=density,
        cohort_terminal_count=len(created_in_window & terminal_by_end),
        churn_rate=None if not created_in_window else _finite(len(created_in_window & terminal_by_end) / len(created_in_window), field_name="churn_rate"),
        outcomes=tuple(outcomes),
    )


def compute_candidate_metrics(replay: CandidateReplay, capsule: SourceCapsule, *, config: CalibrationConfig) -> CandidateMetrics:
    if capsule.stage.value != "development":
        raise ContractValidationError("development metrics require a development capsule")
    folds = tuple(
        compute_window_metrics(replay, capsule, config=config, name=fold.name, start=fold.start, end=fold.end)
        for fold in config.development_folds
    )
    pooled = compute_window_metrics(
        replay,
        capsule,
        config=config,
        name="development_pooled",
        start=config.development_folds[0].start,
        end=config.development_folds[-1].end,
    )
    return CandidateMetrics(period=replay.period, folds=folds, pooled=pooled)


def median_absolute_deviation(values: tuple[float, ...] | list[float]) -> float | None:
    if not values:
        return None
    center = median(values)
    return _finite(median([abs(value - center) for value in values]), field_name="median_absolute_deviation")


__all__ = [
    "CandidateMetrics",
    "FirstTouchOutcome",
    "WindowMetrics",
    "WINDOW_POLICY",
    "compute_candidate_metrics",
    "compute_window_metrics",
    "median_absolute_deviation",
]
