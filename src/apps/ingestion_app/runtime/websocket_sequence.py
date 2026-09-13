"""Consumed sequence and causal liveness state for one live websocket."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Literal

from apps.ingestion_app.domain.candle import CandleObservation
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.services.time_alignment import aligned_bucket_start


def _same_live_observation(
    first: CandleObservation,
    second: CandleObservation,
) -> bool:
    return (
        first.lane == second.lane
        and first.provider_id == second.provider_id
        and first.provider_symbol == second.provider_symbol
        and first.transport == second.transport
        and first.open_time == second.open_time
        and first.close_time == second.close_time
        and first.open == second.open
        and first.high == second.high
        and first.low == second.low
        and first.close == second.close
        and first.volume == second.volume
        and first.taker_buy_base == second.taker_buy_base
        and first.provider_close_time == second.provider_close_time
        and first.provider_event_id == second.provider_event_id
    )


def _build_recovery_requests(
    *,
    routes: Mapping[str, tuple[MarketLane, str]],
    last_consumed_close: Mapping[MarketLane, datetime],
    connection_anchor: datetime,
    interruption_time: datetime,
    timeframe_duration: timedelta,
    alignment_origin: datetime,
    reason: str,
) -> tuple[RecoveryRequest, ...]:
    recovery_until = aligned_bucket_start(
        interruption_time,
        timeframe_duration,
        alignment_origin,
    )
    requests: list[RecoveryRequest] = []
    ordered_routes = sorted(
        routes.values(),
        key=lambda route: (
            route[0].venue,
            route[0].instrument_id,
            route[0].timeframe,
        ),
    )
    for lane, _provider_symbol in ordered_routes:
        recovery_since = last_consumed_close.get(lane, connection_anchor)
        if recovery_since < recovery_until:
            requests.append(
                RecoveryRequest(
                    lane=lane,
                    since=recovery_since,
                    until=recovery_until,
                    reason=reason,
                )
            )
    return tuple(requests)


def _silence_deadline(
    *,
    last_consumed_close: datetime | None,
    connection_anchor: datetime,
    timeframe_duration: timedelta,
) -> datetime:
    """Return the causal finalized-progress deadline for one lane."""
    last_close = (
        connection_anchor if last_consumed_close is None else last_consumed_close
    )
    return last_close + 2 * timeframe_duration


def _ordered_silence_deadlines(
    *,
    routes: Mapping[str, tuple[MarketLane, str]],
    last_consumed_close: Mapping[MarketLane, datetime],
    connection_anchor: datetime,
    timeframe_duration: timedelta,
) -> tuple[tuple[MarketLane, datetime], ...]:
    ordered_routes = sorted(
        routes.values(),
        key=lambda route: (
            route[0].venue,
            route[0].instrument_id,
            route[0].timeframe,
        ),
    )
    return tuple(
        (
            lane,
            _silence_deadline(
                last_consumed_close=last_consumed_close.get(lane),
                connection_anchor=connection_anchor,
                timeframe_duration=timeframe_duration,
            ),
        )
        for lane, _provider_symbol in ordered_routes
    )


def _earliest_silence_deadline(
    *,
    routes: Mapping[str, tuple[MarketLane, str]],
    last_consumed_close: Mapping[MarketLane, datetime],
    connection_anchor: datetime,
    timeframe_duration: timedelta,
) -> tuple[MarketLane, datetime]:
    """Select the earliest lane deadline with deterministic tie ordering."""
    return min(
        _ordered_silence_deadlines(
            routes=routes,
            last_consumed_close=last_consumed_close,
            connection_anchor=connection_anchor,
            timeframe_duration=timeframe_duration,
        ),
        key=lambda item: (
            item[1],
            item[0].venue,
            item[0].instrument_id,
            item[0].timeframe,
        ),
    )


def _overdue_silence_lanes(
    *,
    routes: Mapping[str, tuple[MarketLane, str]],
    last_consumed_close: Mapping[MarketLane, datetime],
    connection_anchor: datetime,
    timeframe_duration: timedelta,
    now: datetime,
) -> tuple[MarketLane, ...]:
    """Return lanes at or beyond their causal silence deadline."""
    return tuple(
        lane
        for lane, deadline in _ordered_silence_deadlines(
            routes=routes,
            last_consumed_close=last_consumed_close,
            connection_anchor=connection_anchor,
            timeframe_duration=timeframe_duration,
        )
        if now >= deadline
    )


@dataclass(frozen=True, slots=True)
class SequenceDecision:
    """Pure classification of one decoded finalized observation."""

    kind: Literal["deliver", "ignore", "interrupt"]
    reason: str | None = None
    detail: str | None = None


class LiveSequenceTracker:
    """Own consumed sequence and causal liveness state for one connection."""

    def __init__(
        self,
        *,
        routes: Mapping[str, tuple[MarketLane, str]],
        connection_anchor: datetime,
        timeframe_duration: timedelta,
        alignment_origin: datetime,
    ) -> None:
        self._routes = routes
        self._connection_anchor = connection_anchor
        self._timeframe_duration = timeframe_duration
        self._alignment_origin = alignment_origin
        self._last_consumed_close: dict[MarketLane, datetime] = {}
        self._last_consumed_observation: dict[MarketLane, CandleObservation] = {}

    @property
    def last_consumed_close(self) -> Mapping[MarketLane, datetime]:
        """Expose a read-only snapshot for diagnostics and direct tests."""
        return MappingProxyType(self._last_consumed_close)

    @property
    def last_consumed_observation(
        self,
    ) -> Mapping[MarketLane, CandleObservation]:
        """Expose the consumed observations without granting mutation."""
        return MappingProxyType(self._last_consumed_observation)

    def classify(self, observation: CandleObservation) -> SequenceDecision:
        """Classify without mutating consumed sequence/liveness state."""
        previous = self._last_consumed_observation.get(observation.lane)
        if previous is None:
            if observation.close_time <= self._connection_anchor:
                return SequenceDecision(kind="ignore")
            if observation.open_time < self._connection_anchor:
                return SequenceDecision(
                    kind="interrupt",
                    reason="websocket_malformed_payload",
                    detail="older out-of-order candle preceded live progress",
                )
            if observation.open_time != self._connection_anchor:
                return SequenceDecision(
                    kind="interrupt",
                    reason="websocket_gap_detected",
                    detail="first live candle did not begin at the connection anchor",
                )
        elif _same_live_observation(observation, previous):
            return SequenceDecision(kind="ignore")
        elif observation.open_time < previous.close_time:
            return SequenceDecision(
                kind="interrupt",
                reason="websocket_malformed_payload",
                detail="older out-of-order finalized candle received",
            )
        elif observation.open_time > previous.close_time:
            return SequenceDecision(
                kind="interrupt",
                reason="websocket_gap_detected",
                detail="finalized live candle gap detected",
            )
        return SequenceDecision(kind="deliver")

    def record_consumed(self, observation: CandleObservation) -> None:
        """Advance state after the caller resumes from its async-generator yield."""
        self._last_consumed_close[observation.lane] = observation.close_time
        self._last_consumed_observation[observation.lane] = observation

    def recovery_requests(
        self,
        reason: str,
        *,
        interruption_time: datetime,
    ) -> tuple[RecoveryRequest, ...]:
        return _build_recovery_requests(
            routes=self._routes,
            last_consumed_close=self._last_consumed_close,
            connection_anchor=self._connection_anchor,
            interruption_time=interruption_time,
            timeframe_duration=self._timeframe_duration,
            alignment_origin=self._alignment_origin,
            reason=reason,
        )

    def earliest_silence_deadline(self) -> tuple[MarketLane, datetime]:
        return _earliest_silence_deadline(
            routes=self._routes,
            last_consumed_close=self._last_consumed_close,
            connection_anchor=self._connection_anchor,
            timeframe_duration=self._timeframe_duration,
        )

    def overdue_silence_lanes(self, now: datetime) -> tuple[MarketLane, ...]:
        return _overdue_silence_lanes(
            routes=self._routes,
            last_consumed_close=self._last_consumed_close,
            connection_anchor=self._connection_anchor,
            timeframe_duration=self._timeframe_duration,
            now=now,
        )


__all__ = [
    "LiveSequenceTracker",
    "SequenceDecision",
    "_build_recovery_requests",
    "_earliest_silence_deadline",
    "_overdue_silence_lanes",
    "_same_live_observation",
    "_silence_deadline",
]
