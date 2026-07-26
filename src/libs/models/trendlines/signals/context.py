"""Typed, point-in-time contracts for native trendline signals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import pandas as pd

from libs.models.trendlines.boundary.contracts import BoundaryResult
from libs.models.trendlines.boundary.history import TrendlineSnapshot
from libs.models.trendlines.contracts.identity import (
    TrendlineSnapshotStage,
    canonical_hash,
    canonical_point_text,
    resolve_source_horizon,
)


SIGNAL_INPUT_ID_SEMANTICS_VERSION = "trendlines.signal-input-id.v1"


class BarTimestampSemantics(str, Enum):
    """Meaning of each current-frame event timestamp."""

    OPEN_TIME = "open_time"
    CLOSE_TIME = "close_time"


class BarAvailabilitySource(str, Enum):
    """Source used to establish completed-bar availability."""

    EXCHANGE_CLOSE_TIME = "exchange_close_time"
    FIXED_INTERVAL_DERIVED = "fixed_interval_derived"
    CLOSE_TIME_INDEX = "close_time_index"


class SignalContextContractError(ValueError):
    """Raised when current-frame signal context is malformed."""


class SignalHistoryContractError(ValueError):
    """Raised when signal history violates point-in-time contracts."""


class SignalAvailabilityError(SignalContextContractError):
    """Raised when a bar is unavailable at declared query knowledge time."""


def _utc_datetime(value: Any, *, name: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif hasattr(value, "to_pydatetime"):
        result = value.to_pydatetime()
    else:
        raise SignalContextContractError(f"{name} must be datetime-like")
    if result.tzinfo is None or result.utcoffset() is None:
        raise SignalContextContractError(f"{name} must be timezone-aware")
    return result.astimezone(timezone.utc)


def _utc_index(value: Any, *, name: str) -> pd.DatetimeIndex:
    if not isinstance(value, pd.DatetimeIndex):
        raise SignalContextContractError(f"{name} must be a DatetimeIndex")
    if value.tz is None:
        raise SignalContextContractError(f"{name} must be timezone-aware")
    result = value.tz_convert("UTC")
    if len(result) == 0:
        raise SignalContextContractError(f"{name} must be non-empty")
    if not result.is_monotonic_increasing:
        raise SignalContextContractError(f"{name} must be monotonic increasing")
    if not result.is_unique:
        raise SignalContextContractError(f"{name} must be unique")
    return result


@dataclass(frozen=True)
class TrendlineSignalContext:
    """Availability and timestamp semantics for one signal execution."""

    known_at: datetime
    bar_available_at: pd.DatetimeIndex
    timestamp_semantics: BarTimestampSemantics
    volume_is_trustworthy: bool
    availability_source: BarAvailabilitySource = BarAvailabilitySource.FIXED_INTERVAL_DERIVED

    def __post_init__(self) -> None:
        known_at = _utc_datetime(self.known_at, name="known_at")
        available = _utc_index(self.bar_available_at, name="bar_available_at")
        if not isinstance(self.timestamp_semantics, BarTimestampSemantics):
            raise SignalContextContractError(
                "timestamp_semantics must be a BarTimestampSemantics"
            )
        if not isinstance(self.availability_source, BarAvailabilitySource):
            raise SignalContextContractError(
                "availability_source must be a BarAvailabilitySource"
            )
        if not isinstance(self.volume_is_trustworthy, bool):
            raise SignalContextContractError(
                "volume_is_trustworthy must be a bool"
            )
        if available[-1].to_pydatetime() > known_at:
            raise SignalAvailabilityError(
                "final bar availability must be <= signal query known_at"
            )
        object.__setattr__(self, "known_at", known_at)
        object.__setattr__(self, "bar_available_at", available)

    @classmethod
    def from_close_time_index(
        cls,
        index: pd.DatetimeIndex,
        *,
        volume_is_trustworthy: bool,
    ) -> "TrendlineSignalContext":
        close_times = _utc_index(index, name="close-time index")
        return cls(
            known_at=close_times[-1].to_pydatetime(),
            bar_available_at=close_times,
            timestamp_semantics=BarTimestampSemantics.CLOSE_TIME,
            volume_is_trustworthy=volume_is_trustworthy,
            availability_source=BarAvailabilitySource.CLOSE_TIME_INDEX,
        )


@dataclass(frozen=True)
class TrendlineSignalInputs:
    """Validated input envelope for native trendline signal extraction."""

    context: TrendlineSignalContext
    history: tuple[TrendlineSnapshot, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.context, TrendlineSignalContext):
            raise SignalContextContractError(
                "context must be a TrendlineSignalContext"
            )
        history = tuple(self.history)
        for snapshot in history:
            if not isinstance(snapshot, TrendlineSnapshot):
                raise SignalHistoryContractError(
                    "signal history must contain TrendlineSnapshot revisions"
                )
        object.__setattr__(self, "history", history)


@dataclass(frozen=True)
class ValidatedTrendlineSignalInputs:
    """Single validation result shared by all signal extractors."""

    inputs: TrendlineSignalInputs
    history_boundaries: tuple[BoundaryResult, ...]
    signal_input_id: str
    signal_available_at: datetime
    boundary_snapshot_id: str
    checkpoint_id: str
    source_id: str

    @property
    def context(self) -> TrendlineSignalContext:
        return self.inputs.context

    @property
    def history(self) -> tuple[TrendlineSnapshot, ...]:
        return self.inputs.history

    def metadata(self) -> dict[str, Any]:
        return {
            "signal_input_id": self.signal_input_id,
            "signal_boundary_snapshot_id": self.boundary_snapshot_id,
            "signal_checkpoint_id": self.checkpoint_id,
            "signal_source_id": self.source_id,
            "signal_query_known_at": self.context.known_at.isoformat(),
            "signal_available_at": self.signal_available_at.isoformat(),
            "history_snapshot_ids": [
                snapshot.snapshot_identity.snapshot_id
                for snapshot in self.history
            ],
            "history_revision_ids": [
                snapshot.snapshot_identity.revision_id
                for snapshot in self.history
            ],
            "bar_timestamp_semantics": self.context.timestamp_semantics.value,
            "bar_availability_source": self.context.availability_source.value,
        }


def validate_signal_inputs(
    frame: pd.DataFrame,
    boundary: BoundaryResult,
    signal_inputs: TrendlineSignalInputs,
) -> ValidatedTrendlineSignalInputs:
    """Validate one signal envelope against current boundary and exact frame."""

    if not isinstance(boundary, BoundaryResult):
        raise SignalContextContractError("boundary must be a BoundaryResult")
    if not isinstance(signal_inputs, TrendlineSignalInputs):
        raise SignalContextContractError(
            "signal_inputs must be a TrendlineSignalInputs"
        )
    if not isinstance(frame, pd.DataFrame):
        raise SignalContextContractError("frame must be a pandas DataFrame")

    context = signal_inputs.context
    current_event = _utc_datetime(boundary.timestamp, name="boundary timestamp")
    frame_horizon = _validate_current_frame(frame, boundary, context)
    identity = _validate_current_boundary_identity(boundary, frame_horizon)

    seen_ids: set[str] = set()
    seen_events: set[datetime] = set()
    previous_event: datetime | None = None
    boundaries: list[BoundaryResult] = []
    for snapshot in signal_inputs.history:
        snapshot_identity = snapshot.snapshot_identity
        if snapshot_identity is None:
            raise SignalHistoryContractError(
                "signal history snapshots require snapshot identity"
            )
        if snapshot_identity.stage is not TrendlineSnapshotStage.BOUNDARY:
            raise SignalHistoryContractError(
                "signal history snapshots must be boundary-stage identities"
            )
        if (
            snapshot_identity.asset != snapshot.boundary.asset
            or snapshot_identity.timeframe != snapshot.boundary.timeframe
            or snapshot.timestamp != snapshot.boundary.timestamp
        ):
            raise SignalHistoryContractError(
                "signal history identity does not match its boundary"
            )
        if snapshot.asset.upper() != boundary.asset.upper():
            raise SignalHistoryContractError("signal history asset does not match current boundary")
        if snapshot.timeframe != boundary.timeframe:
            raise SignalHistoryContractError(
                "signal history timeframe does not match current boundary"
            )
        snapshot_event = _utc_datetime(snapshot.timestamp, name="history timestamp")
        if snapshot_event >= current_event:
            raise SignalHistoryContractError(
                "signal history event must precede current boundary event"
            )
        if snapshot.known_at is None or snapshot.known_at > context.known_at:
            raise SignalHistoryContractError(
                "signal history revision was not known at query time"
            )
        if (
            snapshot_identity.checkpoint.source.as_of
            != canonical_point_text(snapshot.boundary.timestamp)
        ):
            raise SignalHistoryContractError(
                "signal history identity horizon does not match boundary timestamp"
            )
        if snapshot_identity.snapshot_id in seen_ids:
            raise SignalHistoryContractError("signal history contains duplicate snapshot IDs")
        if snapshot_event in seen_events:
            raise SignalHistoryContractError(
                "signal history contains duplicate event timestamps"
            )
        if previous_event is not None and snapshot_event <= previous_event:
            raise SignalHistoryContractError(
                "signal history must be strictly increasing by event time"
            )
        seen_ids.add(snapshot_identity.snapshot_id)
        seen_events.add(snapshot_event)
        previous_event = snapshot_event
        boundaries.append(snapshot.boundary)

    current_available = context.bar_available_at[-1].to_pydatetime()
    signal_available_at = max(
        [current_available, *(snapshot.known_at for snapshot in signal_inputs.history)]
    )
    signal_input_id = build_signal_input_id(boundary, signal_inputs)
    return ValidatedTrendlineSignalInputs(
        inputs=signal_inputs,
        history_boundaries=tuple(boundaries),
        signal_input_id=signal_input_id,
        signal_available_at=signal_available_at,
        boundary_snapshot_id=identity.snapshot_id,
        checkpoint_id=identity.checkpoint.checkpoint_id,
        source_id=identity.checkpoint.source.source_id,
    )


def _validate_current_frame(
    frame: pd.DataFrame,
    boundary: BoundaryResult,
    context: TrendlineSignalContext,
) -> tuple[str, str, int, tuple[str, ...]]:
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise SignalContextContractError("signal frame index must be a DatetimeIndex")
    if frame.empty:
        raise SignalContextContractError("signal frame must be non-empty")
    if frame.index.tz is None:
        raise SignalContextContractError("signal frame index must be timezone-aware")
    event_index = frame.index.tz_convert("UTC")
    if not event_index.is_monotonic_increasing or not event_index.is_unique:
        raise SignalContextContractError(
            "signal frame index must be monotonic increasing and unique"
        )
    if not frame.columns.is_unique:
        raise SignalContextContractError("signal frame columns must be unique")

    available = context.bar_available_at
    if len(available) != len(frame):
        raise SignalContextContractError(
            "bar_available_at length must equal signal frame length"
        )
    if (available > context.known_at).any():
        raise SignalAvailabilityError(
            "a bar is unavailable at signal query known_at"
        )

    event_values = event_index.view("int64")
    available_values = available.view("int64")
    if (available_values < event_values).any():
        raise SignalAvailabilityError(
            "bar availability cannot precede event timestamp"
        )
    if context.timestamp_semantics is BarTimestampSemantics.OPEN_TIME:
        if not (available_values > event_values).all():
            raise SignalAvailabilityError(
                "open-time bars require strictly later availability timestamps"
            )
    elif not (available_values == event_values).all():
        raise SignalAvailabilityError(
            "close-time bars require availability equal to event timestamp"
        )

    boundary_event = _utc_datetime(boundary.timestamp, name="boundary timestamp")
    if event_index[-1].to_pydatetime() != boundary_event:
        raise SignalContextContractError(
            "signal frame final event timestamp does not match boundary timestamp"
        )

    try:
        return resolve_source_horizon(frame)
    except (TypeError, ValueError) as exc:
        raise SignalContextContractError(str(exc)) from exc


def _validate_current_boundary_identity(
    boundary: BoundaryResult,
    frame_horizon: tuple[str, str, int, tuple[str, ...]],
):
    identity = boundary.snapshot_identity
    if identity is None:
        raise SignalContextContractError(
            "current boundary requires a snapshot identity"
        )
    if identity.stage is not TrendlineSnapshotStage.BOUNDARY:
        raise SignalContextContractError(
            "current boundary identity must be boundary-stage"
        )
    if identity.asset != boundary.asset:
        raise SignalContextContractError(
            "current boundary identity asset does not match boundary"
        )
    if identity.timeframe != boundary.timeframe:
        raise SignalContextContractError(
            "current boundary identity timeframe does not match boundary"
        )

    source = identity.checkpoint.source
    source_start, source_as_of, row_count, columns = frame_horizon
    if source.as_of != canonical_point_text(boundary.timestamp):
        raise SignalContextContractError(
            "current boundary identity horizon does not match boundary timestamp"
        )
    if source.as_of != source_as_of:
        raise SignalContextContractError(
            "current boundary checkpoint as_of does not match signal frame"
        )
    if source.source_start != source_start:
        raise SignalContextContractError(
            "current boundary checkpoint source_start does not match signal frame"
        )
    if source.row_count != row_count:
        raise SignalContextContractError(
            "current boundary checkpoint row_count does not match signal frame"
        )
    if source.columns != columns:
        raise SignalContextContractError(
            "current boundary checkpoint columns do not match signal frame"
        )
    return identity


def build_signal_input_id(
    boundary: BoundaryResult,
    signal_inputs: TrendlineSignalInputs,
) -> str:
    """Build deterministic identity for selected signal inputs."""

    identity = boundary.snapshot_identity
    if identity is None:
        raise SignalContextContractError(
            "signal input identity requires an identity-bearing current boundary"
        )
    if identity.stage is not TrendlineSnapshotStage.BOUNDARY:
        raise SignalContextContractError(
            "signal input identity requires a boundary-stage current boundary"
        )
    if identity.asset != boundary.asset or identity.timeframe != boundary.timeframe:
        raise SignalContextContractError(
            "signal input identity scope does not match current boundary"
        )
    if identity.checkpoint.source.as_of != canonical_point_text(boundary.timestamp):
        raise SignalContextContractError(
            "signal input identity horizon does not match current boundary"
        )
    checkpoint_id = identity.checkpoint.checkpoint_id
    source_id = identity.checkpoint.source.source_id
    payload = {
        "checkpoint_id": checkpoint_id,
        "source_id": source_id,
        "boundary_as_of": canonical_point_text(boundary.timestamp),
        "timestamp_semantics": signal_inputs.context.timestamp_semantics.value,
        "query_known_at": signal_inputs.context.known_at.isoformat(),
        "final_bar_available_at": signal_inputs.context.bar_available_at[-1].isoformat(),
        "volume_is_trustworthy": signal_inputs.context.volume_is_trustworthy,
        "history": [
            {
                "snapshot_id": snapshot.snapshot_identity.snapshot_id,
                "revision_id": snapshot.snapshot_identity.revision_id,
                "known_at": snapshot.known_at.isoformat(),
            }
            for snapshot in signal_inputs.history
            if snapshot.snapshot_identity is not None
        ],
    }
    if any(snapshot.snapshot_identity is None for snapshot in signal_inputs.history):
        raise SignalHistoryContractError(
            "signal input identity requires identity-bearing history snapshots"
        )
    return canonical_hash(payload, semantics_version=SIGNAL_INPUT_ID_SEMANTICS_VERSION)


__all__ = [
    "BarAvailabilitySource",
    "BarTimestampSemantics",
    "SIGNAL_INPUT_ID_SEMANTICS_VERSION",
    "SignalAvailabilityError",
    "SignalContextContractError",
    "SignalHistoryContractError",
    "TrendlineSignalContext",
    "TrendlineSignalInputs",
    "ValidatedTrendlineSignalInputs",
    "build_signal_input_id",
    "validate_signal_inputs",
]
