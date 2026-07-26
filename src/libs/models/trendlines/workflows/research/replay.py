"""Causal, prefix-only execution for prepared trendline research data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import pandas as pd
import numpy as np

from libs.models.trendlines.api import (
    TrendlineOutput,
    fit_and_signal,
    fit_trendlines_to_boundary,
)
from libs.models.trendlines.boundary.history import (
    TrendlineSnapshot,
    TrendlineSnapshotHistory,
)
from libs.models.trendlines.config.base_config import TrendlinePipelineConfig
from libs.models.trendlines.contracts.identity import (
    TrendlineSnapshotStage,
    TrendlineSourceRef,
    canonical_hash,
    canonical_point_text,
    resolve_source_ref,
)
from libs.models.trendlines.pivots.capabilities import TrendlineExecutionMode
from libs.models.trendlines.signals.context import (
    BarAvailabilitySource,
    BarTimestampSemantics,
    TrendlineSignalContext,
    TrendlineSignalInputs,
)
from libs.models.trendlines.workflows.research.contracts import (
    PreparedTrendlineResearchRun,
    TrendlineReplayContractError,
    TrendlineReplayWindow,
    TrendlineResearchReplaySpec,
)


RESEARCH_REPLAY_SEMANTICS_VERSION = "trendlines.research-replay.v1"
REPLAY_POINT_SEMANTICS_VERSION = "trendlines.research-replay-point.v1"
REPLAY_POINT_CONTENT_SEMANTICS_VERSION = (
    "trendlines.research-replay-point-content.v1"
)


class TrendlineReplayError(RuntimeError):
    """Raised when one causal replay position cannot be executed."""

    def __init__(
        self,
        *,
        timeframe: str,
        position: int,
        event_at: Any,
        available_at: Any,
        cause: BaseException,
    ) -> None:
        self.timeframe = timeframe
        self.position = position
        self.event_at = canonical_point_text(event_at)
        self.available_at = canonical_point_text(available_at)
        self.underlying_error_type = type(cause).__name__
        super().__init__(
            "Causal replay failed: "
            f"timeframe={timeframe}, position={position}, "
            f"event_at={self.event_at}, available_at={self.available_at}, "
            f"error_type={self.underlying_error_type}"
        )


class TrendlineReplayIntegrityError(ValueError):
    """Raised when replay content no longer matches its stored identities."""


def _as_datetime(value: Any) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise TrendlineReplayContractError("replay timestamps must be timezone-aware")
    return timestamp.tz_convert("UTC").to_pydatetime()


def _serialized_signal_output(value: Any) -> Any:
    """Normalize AlphaSignal objects nested in orchestrator output."""

    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _serialized_signal_output(value.to_dict())
    if isinstance(value, dict):
        return {str(key): _serialized_signal_output(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialized_signal_output(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _serialized_signal_output(value.item())
    if isinstance(value, np.ndarray):
        return _serialized_signal_output(value.tolist())
    if isinstance(value, float) and not np.isfinite(value):
        return str(value)
    return value


def _compact_boundary_content(boundary: Any) -> dict[str, Any]:
    quality = boundary.quality_metrics
    return {
        "asset": boundary.asset,
        "timeframe": boundary.timeframe,
        "timestamp": str(boundary.timestamp),
        "active_support_rays": [ray.to_dict() for ray in boundary.active_support_rays],
        "active_resistance_rays": [
            ray.to_dict() for ray in boundary.active_resistance_rays
        ],
        "convex_hull_floor": boundary.convex_hull_floor,
        "convex_hull_ceiling": boundary.convex_hull_ceiling,
        "interaction": boundary.interaction,
        "is_valid": boundary.is_valid,
        "quality_metrics": asdict(quality) if quality is not None else None,
        "boundary_context": _serialized_signal_output(boundary.boundary_context),
        "metadata": _serialized_signal_output(dict(boundary.metadata)),
        "snapshot_identity": (
            boundary.snapshot_identity.to_dict()
            if boundary.snapshot_identity is not None
            else None
        ),
    }


def _compact_snapshot_content(snapshot: TrendlineSnapshot) -> dict[str, Any]:
    return {
        "asset": snapshot.asset,
        "timeframe": snapshot.timeframe,
        "timestamp": str(snapshot.timestamp),
        "known_at": snapshot.known_at.isoformat(),
        "boundary": _compact_boundary_content(snapshot.boundary),
        "metadata": _serialized_signal_output(dict(snapshot.metadata)),
        "snapshot_identity": (
            snapshot.snapshot_identity.to_dict()
            if snapshot.snapshot_identity is not None
            else None
        ),
    }


def _compact_output_content(output: TrendlineOutput) -> dict[str, Any]:
    fit = output.fit_result
    return {
        "fit_result": {
            "support_lines": [line.to_dict() for line in fit.support_lines],
            "resistance_lines": [line.to_dict() for line in fit.resistance_lines],
            "is_valid": fit.is_valid,
            "metadata": _serialized_signal_output(dict(fit.metadata)),
            "checkpoint": fit.checkpoint.to_dict() if fit.checkpoint else None,
            "snapshot_identity": (
                fit.snapshot_identity.to_dict() if fit.snapshot_identity else None
            ),
        },
        "signal_output": _serialized_signal_output(output.signal_output),
        "config": output.config.to_dict() if output.config else None,
        "metadata": _serialized_signal_output(dict(output.metadata)),
        "checkpoint": output.checkpoint.to_dict() if output.checkpoint else None,
        "snapshot_identity": (
            output.snapshot_identity.to_dict() if output.snapshot_identity else None
        ),
    }


@dataclass(frozen=True)
class TrendlineReplayPoint:
    """One recorded output produced from one exact prepared-data prefix."""

    timeframe: str
    position: int
    event_at: datetime
    available_at: datetime
    prefix_source_ref: TrendlineSourceRef
    output: TrendlineOutput
    boundary_snapshot: TrendlineSnapshot
    content_id: str
    replay_point_id: str

    @property
    def boundary_identity(self) -> Any:
        return self.boundary_snapshot.snapshot_identity

    @property
    def fit_snapshot_id(self) -> str | None:
        identity = self.output.fit_result.snapshot_identity
        return identity.snapshot_id if identity is not None else None

    @property
    def fit_revision_id(self) -> str | None:
        identity = self.output.fit_result.snapshot_identity
        return identity.revision_id if identity is not None else None

    @property
    def signal_identity(self) -> Any:
        identity = self.output.snapshot_identity
        if identity is not None and identity.stage is TrendlineSnapshotStage.SIGNAL:
            return identity
        return None

    def to_dict(self) -> dict[str, Any]:
        validate_replay_point_integrity(self)
        return {
            "timeframe": self.timeframe,
            "position": self.position,
            "event_at": self.event_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "prefix_source_ref": self.prefix_source_ref.to_dict(),
            "output": _serialized_signal_output(self.output.to_dict()),
            "boundary_snapshot": self.boundary_snapshot.to_dict(),
            "content_id": self.content_id,
            "replay_point_id": self.replay_point_id,
        }


@dataclass(frozen=True)
class TrendlineTimeframeReplay:
    """Recorded points plus executed-position accounting for one timeframe."""

    timeframe: str
    points: tuple[TrendlineReplayPoint, ...]
    executed_positions: tuple[int, ...]
    warmup_position_count: int
    peak_retained_history_count: int = 0

    def __post_init__(self) -> None:
        positions = tuple(point.position for point in self.points)
        if positions != tuple(sorted(positions)) or len(set(positions)) != len(positions):
            raise TrendlineReplayContractError("replay points must be ordered and unique")
        if self.warmup_position_count < 0:
            raise TrendlineReplayContractError("warmup_position_count must be >= 0")
        if self.peak_retained_history_count < 0:
            raise TrendlineReplayContractError(
                "peak_retained_history_count must be >= 0"
            )

    @property
    def recorded_positions(self) -> tuple[int, ...]:
        return tuple(point.position for point in self.points)

    @property
    def executed_position_count(self) -> int:
        return len(self.executed_positions)

    @property
    def recorded_position_count(self) -> int:
        return len(self.points)

    def output_at(self, position: int) -> TrendlineReplayPoint:
        for point in self.points:
            if point.position == position:
                validate_replay_point_integrity(point)
                return point
        raise TrendlineReplayContractError(
            f"position {position} was not recorded for timeframe {self.timeframe}"
        )

    def latest(self) -> TrendlineReplayPoint:
        if not self.points:
            raise TrendlineReplayContractError(
                f"no recorded replay points for timeframe {self.timeframe}"
            )
        return self.output_at(self.points[-1].position)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "points": [point.to_dict() for point in self.points],
            "executed_positions": list(self.executed_positions),
            "warmup_position_count": self.warmup_position_count,
            "recorded_positions": list(self.recorded_positions),
            "peak_retained_history_count": self.peak_retained_history_count,
        }


@dataclass(frozen=True)
class PreparedTrendlineResearchReplay:
    """Causal replay across prepared timeframes."""

    prepared: PreparedTrendlineResearchRun
    replay_spec: TrendlineResearchReplaySpec
    replay_id: str
    timeframes: Mapping[str, TrendlineTimeframeReplay]

    def __post_init__(self) -> None:
        expected = tuple(self.prepared.spec.timeframes)
        values = dict(self.timeframes)
        if tuple(values) != expected:
            raise TrendlineReplayContractError(
                "replay timeframes must preserve prepared timeframe order"
            )
        object.__setattr__(self, "timeframes", values)

    @property
    def preparation_id(self) -> str:
        return self.prepared.preparation_id

    @property
    def dataset_id(self) -> str:
        return self.prepared.dataset.dataset_id

    @property
    def research_configuration_id(self) -> str:
        return self.prepared.configuration.research_configuration_id

    def output_at(self, timeframe: str, position: int) -> TrendlineReplayPoint:
        try:
            replay = self.timeframes[timeframe]
        except KeyError as exc:
            raise TrendlineReplayContractError(
                f"timeframe {timeframe!r} is absent from replay"
            ) from exc
        return replay.output_at(position)

    def latest(self, timeframe: str) -> TrendlineReplayPoint:
        return self.timeframes[timeframe].latest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "preparation_id": self.preparation_id,
            "dataset_id": self.dataset_id,
            "research_configuration_id": self.research_configuration_id,
            "replay_spec": self.replay_spec.to_dict(),
            "replay_id": self.replay_id,
            "timeframes": {
                timeframe: self.timeframes[timeframe].to_dict()
                for timeframe in self.timeframes
            },
            "semantics_version": RESEARCH_REPLAY_SEMANTICS_VERSION,
        }


def _integrity_failure(message: str) -> TrendlineReplayIntegrityError:
    return TrendlineReplayIntegrityError(f"replay point integrity failure: {message}")


def validate_replay_point_integrity(point: TrendlineReplayPoint) -> None:
    """Verify stored replay identities against current nested output content."""

    if not isinstance(point, TrendlineReplayPoint):
        raise TypeError("point must be a TrendlineReplayPoint")
    boundary_identity = point.boundary_snapshot.snapshot_identity
    output_boundary = point.output.boundary_result
    output_checkpoint = point.output.checkpoint
    fit_identity = point.output.fit_result.snapshot_identity
    fit_checkpoint = point.output.fit_result.checkpoint
    if boundary_identity is None:
        raise _integrity_failure("boundary snapshot has no identity")
    if output_boundary is None or output_boundary.snapshot_identity is None:
        raise _integrity_failure("output boundary has no identity")
    if output_boundary.snapshot_identity != boundary_identity:
        raise _integrity_failure("output boundary identity differs from stored snapshot")
    if point.boundary_snapshot.boundary.snapshot_identity != boundary_identity:
        raise _integrity_failure("stored boundary identity differs from snapshot identity")
    if point.prefix_source_ref.source_id != boundary_identity.checkpoint.source.source_id:
        raise _integrity_failure("prefix source differs from boundary checkpoint source")
    if boundary_identity.checkpoint.source.row_count != point.position + 1:
        raise _integrity_failure("checkpoint row count differs from replay position")
    if boundary_identity.checkpoint.source.as_of != point.event_at.isoformat():
        raise _integrity_failure("checkpoint horizon differs from replay event time")
    if output_checkpoint != boundary_identity.checkpoint:
        raise _integrity_failure("output checkpoint differs from boundary checkpoint")
    if fit_checkpoint != boundary_identity.checkpoint:
        raise _integrity_failure("fit checkpoint differs from boundary checkpoint")
    if fit_identity is None or fit_identity.stage is not TrendlineSnapshotStage.FIT:
        raise _integrity_failure("fit identity is absent or has wrong stage")
    if boundary_identity.stage is not TrendlineSnapshotStage.BOUNDARY:
        raise _integrity_failure("boundary identity has wrong stage")
    if point.output.signal_output is None:
        if (
            point.output.snapshot_identity is None
            or point.output.snapshot_identity != boundary_identity
        ):
            raise _integrity_failure("boundary-only output identity is inconsistent")
    elif (
        point.output.snapshot_identity is None
        or point.output.snapshot_identity.stage is not TrendlineSnapshotStage.SIGNAL
    ):
        raise _integrity_failure("signal output identity is absent or has wrong stage")
    if _compact_boundary_content(output_boundary) != _compact_boundary_content(
        point.boundary_snapshot.boundary
    ):
        raise _integrity_failure("output boundary content differs from stored snapshot")
    current_content_id = _point_content_id(
        timeframe=point.timeframe,
        position=point.position,
        event_at=point.event_at,
        available_at=point.available_at,
        source_ref=point.prefix_source_ref,
        output=point.output,
        boundary_snapshot=point.boundary_snapshot,
    )
    if current_content_id != point.content_id:
        raise _integrity_failure("content_id does not match current point content")
    current_point_id = _point_id(
        timeframe=point.timeframe,
        position=point.position,
        event_at=point.event_at,
        available_at=point.available_at,
        source_ref=point.prefix_source_ref,
        output=point.output,
        boundary_snapshot=point.boundary_snapshot,
        content_id=point.content_id,
    )
    if current_point_id != point.replay_point_id:
        raise _integrity_failure("replay_point_id does not match current point content")


def validated_replay_points(
    replay: PreparedTrendlineResearchReplay,
) -> tuple[TrendlineReplayPoint, ...]:
    """Validate all recorded points once and return deterministic replay order."""

    points: list[TrendlineReplayPoint] = []
    for timeframe in replay.prepared.spec.timeframes:
        for point in replay.timeframes[timeframe].points:
            validate_replay_point_integrity(point)
            points.append(point)
    return tuple(points)


def _prefix_frame(frame: pd.DataFrame, position: int) -> pd.DataFrame:
    prefix = frame.iloc[: position + 1].copy()
    prefix.attrs = dict(frame.attrs)
    prefix["bar_available_at"] = pd.DatetimeIndex(prefix["bar_available_at"]).tz_convert(
        "UTC"
    )
    return prefix


def _source_ref_for_prefix(frame: pd.DataFrame) -> TrendlineSourceRef:
    return resolve_source_ref(frame)


def _build_signal_inputs(
    *,
    prefix: pd.DataFrame,
    prepared: PreparedTrendlineResearchRun,
    timeframe: str,
    history: TrendlineSnapshotHistory,
    pipeline_config: TrendlinePipelineConfig,
) -> TrendlineSignalInputs:
    event_at = _as_datetime(prefix.index[-1])
    available_at = _as_datetime(prefix["bar_available_at"].iloc[-1])
    semantics = BarTimestampSemantics(
        str(prefix.attrs["bar_timestamp_semantics"]).strip().lower()
    )
    availability_source = BarAvailabilitySource(
        str(prefix.attrs["bar_availability_source"]).strip().lower()
    )
    snapshots = history.snapshots_before(
        prepared.spec.asset,
        timeframe,
        event_at,
        known_at=available_at,
        limit=history.context_limit(prepared.spec.asset, timeframe),
    )
    context = TrendlineSignalContext(
        known_at=available_at,
        bar_available_at=pd.DatetimeIndex(prefix["bar_available_at"]),
        timestamp_semantics=semantics,
        volume_is_trustworthy="volume" in prefix.columns,
        availability_source=availability_source,
    )
    return TrendlineSignalInputs(context=context, history=tuple(snapshots))


def _point_id(
    *,
    timeframe: str,
    position: int,
    event_at: datetime,
    available_at: datetime,
    source_ref: TrendlineSourceRef,
    output: TrendlineOutput,
    boundary_snapshot: TrendlineSnapshot,
    content_id: str,
) -> str:
    fit_identity = output.fit_result.snapshot_identity
    boundary_identity = boundary_snapshot.snapshot_identity
    signal_identity = output.snapshot_identity
    if signal_identity is not None and signal_identity.stage is not TrendlineSnapshotStage.SIGNAL:
        signal_identity = None
    if boundary_identity is None:
        raise TrendlineReplayContractError("replay boundary snapshot requires identity")
    payload = {
        "timeframe": timeframe,
        "position": position,
        "event_at": event_at.isoformat(),
        "available_at": available_at.isoformat(),
        "prefix_source_id": source_ref.source_id,
        "checkpoint_id": boundary_identity.checkpoint.checkpoint_id,
        "fit_snapshot_id": fit_identity.snapshot_id if fit_identity else None,
        "fit_revision_id": fit_identity.revision_id if fit_identity else None,
        "boundary_snapshot_id": boundary_identity.snapshot_id,
        "boundary_revision_id": boundary_identity.revision_id,
        "signal_snapshot_id": signal_identity.snapshot_id if signal_identity else None,
        "signal_revision_id": signal_identity.revision_id if signal_identity else None,
        "snapshot_finality": boundary_identity.finality.value,
        "content_id": content_id,
        "semantics_version": REPLAY_POINT_SEMANTICS_VERSION,
    }
    return canonical_hash(payload, semantics_version=REPLAY_POINT_SEMANTICS_VERSION)


def _point_content_id(
    *,
    timeframe: str,
    position: int,
    event_at: datetime,
    available_at: datetime,
    source_ref: TrendlineSourceRef,
    output: TrendlineOutput,
    boundary_snapshot: TrendlineSnapshot,
) -> str:
    payload = {
        "timeframe": timeframe,
        "position": position,
        "event_at": event_at.isoformat(),
        "available_at": available_at.isoformat(),
        "prefix_source_ref": source_ref.to_dict(),
        # BoundaryResult is carried authoritatively by boundary_snapshot below.
        # Compact typed payloads retain mutation-sensitive content without
        # serialising duplicate nested geometry or any frame data.
        "output": _compact_output_content(output),
        "boundary_snapshot": _compact_snapshot_content(boundary_snapshot),
        "semantics_version": REPLAY_POINT_CONTENT_SEMANTICS_VERSION,
    }
    return canonical_hash(
        payload,
        semantics_version=REPLAY_POINT_CONTENT_SEMANTICS_VERSION,
    )


def _execute_position(
    *,
    prepared: PreparedTrendlineResearchRun,
    timeframe: str,
    position: int,
    include_signals: bool,
    history: TrendlineSnapshotHistory,
) -> TrendlineReplayPoint:
    frame = prepared.dataset.frames[timeframe]
    prefix = _prefix_frame(frame, position)
    event_at = _as_datetime(prefix.index[-1])
    available_at = _as_datetime(prefix["bar_available_at"].iloc[-1])
    source_ref = _source_ref_for_prefix(prefix)
    pipeline_config = prepared.configuration.pipeline_configs[timeframe]
    root_config = pipeline_config.trendlines_config
    signal_inputs = None
    if include_signals:
        signal_inputs = _build_signal_inputs(
            prefix=prefix,
            prepared=prepared,
            timeframe=timeframe,
            history=history,
            pipeline_config=pipeline_config,
        )

    if include_signals:
        output = fit_and_signal(
            prefix,
            asset=prepared.spec.asset,
            timeframe=timeframe,
            config=pipeline_config,
            trendline_config=pipeline_config,
            trendlines_config=root_config,
            signal_inputs=signal_inputs,
            execution_mode=TrendlineExecutionMode.RESEARCH,
            as_of=event_at,
            source_ref=source_ref,
        )
    else:
        output = fit_trendlines_to_boundary(
            prefix,
            asset=prepared.spec.asset,
            timeframe=timeframe,
            config=pipeline_config,
            trendline_config=pipeline_config,
            trendlines_config=root_config,
            execution_mode=TrendlineExecutionMode.RESEARCH,
            as_of=event_at,
            source_ref=source_ref,
        )

    boundary = output.boundary_result
    if boundary is None or boundary.snapshot_identity is None:
        raise TrendlineReplayContractError(
            "canonical facade returned boundary without snapshot identity"
        )
    stored = history.add(boundary, known_at=available_at)
    content_id = _point_content_id(
        timeframe=timeframe,
        position=position,
        event_at=event_at,
        available_at=available_at,
        source_ref=source_ref,
        output=output,
        boundary_snapshot=stored,
    )
    replay_point_id = _point_id(
        timeframe=timeframe,
        position=position,
        event_at=event_at,
        available_at=available_at,
        source_ref=source_ref,
        output=output,
        boundary_snapshot=stored,
        content_id=content_id,
    )
    return TrendlineReplayPoint(
        timeframe=timeframe,
        position=position,
        event_at=event_at,
        available_at=available_at,
        prefix_source_ref=source_ref,
        output=output,
        boundary_snapshot=stored,
        content_id=content_id,
        replay_point_id=replay_point_id,
    )


def run_causal_replay(
    prepared: PreparedTrendlineResearchRun,
    replay_spec: TrendlineResearchReplaySpec,
) -> PreparedTrendlineResearchReplay:
    """Execute every required causal prefix and record selected positions."""

    if not isinstance(prepared, PreparedTrendlineResearchRun):
        raise TypeError("prepared must be a PreparedTrendlineResearchRun")
    if not isinstance(replay_spec, TrendlineResearchReplaySpec):
        raise TypeError("replay_spec must be a TrendlineResearchReplaySpec")
    replay_spec.validate_for(prepared)
    replay_id = canonical_hash(
        {
            "preparation_id": prepared.preparation_id,
            "dataset_id": prepared.dataset.dataset_id,
            "research_configuration_id": prepared.configuration.research_configuration_id,
            "timeframe_order": list(prepared.spec.timeframes),
            "replay_spec": replay_spec.to_dict(),
            "semantics_version": RESEARCH_REPLAY_SEMANTICS_VERSION,
        },
        semantics_version=RESEARCH_REPLAY_SEMANTICS_VERSION,
    )

    results: dict[str, TrendlineTimeframeReplay] = {}
    for timeframe in prepared.spec.timeframes:
        window = replay_spec.windows[timeframe]
        pipeline_config = prepared.configuration.pipeline_configs[timeframe]
        history = TrendlineSnapshotHistory.from_config(pipeline_config.trendlines_config)
        points: list[TrendlineReplayPoint] = []
        peak_history_count = 0
        executed_positions = tuple(
            range(window.warmup_start_position, window.end_position + 1)
        )
        for position in executed_positions:
            frame = prepared.dataset.frames[timeframe]
            event_at = frame.index[position]
            available_at = frame["bar_available_at"].iloc[position]
            try:
                point = _execute_position(
                    prepared=prepared,
                    timeframe=timeframe,
                    position=position,
                    include_signals=replay_spec.include_signals,
                    history=history,
                )
            except Exception as exc:
                raise TrendlineReplayError(
                    timeframe=timeframe,
                    position=position,
                    event_at=event_at,
                    available_at=available_at,
                    cause=exc,
                ) from exc
            peak_history_count = max(
                peak_history_count,
                history.revision_count(prepared.spec.asset, timeframe),
            )
            if (
                position >= window.record_start_position
                and (position - window.record_start_position) % window.record_every == 0
            ):
                points.append(point)
        results[timeframe] = TrendlineTimeframeReplay(
            timeframe=timeframe,
            points=tuple(points),
            executed_positions=executed_positions,
            warmup_position_count=window.record_start_position
            - window.warmup_start_position,
            peak_retained_history_count=peak_history_count,
        )
    return PreparedTrendlineResearchReplay(
        prepared=prepared,
        replay_spec=replay_spec,
        replay_id=replay_id,
        timeframes=results,
    )


@dataclass(frozen=True)
class ReplayInvarianceMismatch:
    """Structured mismatch detail for two replay points."""

    field: str
    expected: Any
    actual: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
        }


class ReplayFutureInvarianceError(AssertionError):
    """Raised when shared causal points differ between replay runs."""

    def __init__(self, mismatches: tuple[ReplayInvarianceMismatch, ...]) -> None:
        self.mismatches = mismatches
        super().__init__(
            "future-row invariance failed: "
            + "; ".join(mismatch.field for mismatch in mismatches)
        )


def verify_replay_future_invariance(
    full_replay: PreparedTrendlineResearchReplay,
    truncated_replay: PreparedTrendlineResearchReplay,
    *,
    timeframe: str,
    position: int,
) -> None:
    """Compare all identity/content fields at one shared causal position."""

    def scope_value(
        replay: PreparedTrendlineResearchReplay,
        field: str,
    ) -> Any:
        if field == "asset":
            return replay.prepared.spec.asset
        if field == "research_configuration_id":
            return replay.research_configuration_id
        if field == "pipeline_configuration_id":
            config = replay.prepared.configuration.pipeline_configs[timeframe]
            return canonical_hash(
                config.to_dict(),
                semantics_version="trendlines.research-replay-pipeline-config.v1",
            )
        if field == "timestamp_semantics":
            return replay.prepared.dataset.identity.timestamp_semantics.value
        if field == "availability_source":
            return replay.prepared.dataset.identity.availability_sources[timeframe].value
        if field == "include_signals":
            return replay.replay_spec.include_signals
        if field == "warmup_start_position":
            return replay.replay_spec.windows[timeframe].warmup_start_position
        raise KeyError(field)

    for replay_name, replay in (
        ("full_replay", full_replay),
        ("truncated_replay", truncated_replay),
    ):
        if timeframe not in replay.timeframes:
            raise ReplayFutureInvarianceError(
                (
                    ReplayInvarianceMismatch(
                        field=f"{replay_name}.timeframe",
                        expected=timeframe,
                        actual=tuple(replay.timeframes),
                    ),
                )
            )

    scope_fields = (
        "asset",
        "research_configuration_id",
        "pipeline_configuration_id",
        "timestamp_semantics",
        "availability_source",
        "include_signals",
        "warmup_start_position",
    )
    scope_mismatches = tuple(
        ReplayInvarianceMismatch(
            field=field,
            expected=scope_value(full_replay, field),
            actual=scope_value(truncated_replay, field),
        )
        for field in scope_fields
        if scope_value(full_replay, field) != scope_value(truncated_replay, field)
    )
    if scope_mismatches:
        raise ReplayFutureInvarianceError(scope_mismatches)

    for replay_name, replay in (
        ("full_replay", full_replay),
        ("truncated_replay", truncated_replay),
    ):
        if position not in replay.timeframes[timeframe].recorded_positions:
            raise ReplayFutureInvarianceError(
                (
                    ReplayInvarianceMismatch(
                        field=f"{replay_name}.recorded_position",
                        expected=position,
                        actual=replay.timeframes[timeframe].recorded_positions,
                    ),
                )
            )

    full = full_replay.output_at(timeframe, position)
    truncated = truncated_replay.output_at(timeframe, position)
    fields = {
        "event_at": (full.event_at, truncated.event_at),
        "available_at": (full.available_at, truncated.available_at),
        "prefix_source_id": (
            full.prefix_source_ref.source_id,
            truncated.prefix_source_ref.source_id,
        ),
        "prefix_source_ref": (
            full.prefix_source_ref.to_dict(),
            truncated.prefix_source_ref.to_dict(),
        ),
        "checkpoint_id": (
            full.boundary_identity.checkpoint.checkpoint_id,
            truncated.boundary_identity.checkpoint.checkpoint_id,
        ),
        "fit_snapshot_id": (full.fit_snapshot_id, truncated.fit_snapshot_id),
        "fit_revision_id": (full.fit_revision_id, truncated.fit_revision_id),
        "boundary_snapshot_id": (
            full.boundary_identity.snapshot_id,
            truncated.boundary_identity.snapshot_id,
        ),
        "boundary_revision_id": (
            full.boundary_identity.revision_id,
            truncated.boundary_identity.revision_id,
        ),
        "signal_snapshot_id": (
            full.signal_identity.snapshot_id if full.signal_identity else None,
            truncated.signal_identity.snapshot_id if truncated.signal_identity else None,
        ),
        "signal_revision_id": (
            full.signal_identity.revision_id if full.signal_identity else None,
            truncated.signal_identity.revision_id if truncated.signal_identity else None,
        ),
        "content_id": (full.content_id, truncated.content_id),
        "replay_point_id": (full.replay_point_id, truncated.replay_point_id),
        "point_content": (
            _serialized_signal_output(full.output.to_dict()),
            _serialized_signal_output(truncated.output.to_dict()),
        ),
        "boundary_content": (
            _serialized_signal_output(full.boundary_snapshot.boundary.to_dict()),
            _serialized_signal_output(truncated.boundary_snapshot.boundary.to_dict()),
        ),
        "signal_content": (
            _serialized_signal_output(full.output.signal_output),
            _serialized_signal_output(truncated.output.signal_output),
        ),
    }
    mismatches = tuple(
        ReplayInvarianceMismatch(field=field, expected=left, actual=right)
        for field, (left, right) in fields.items()
        if left != right
    )
    if mismatches:
        raise ReplayFutureInvarianceError(mismatches)


__all__ = [
    "PreparedTrendlineResearchReplay",
    "REPLAY_POINT_CONTENT_SEMANTICS_VERSION",
    "REPLAY_POINT_SEMANTICS_VERSION",
    "RESEARCH_REPLAY_SEMANTICS_VERSION",
    "ReplayFutureInvarianceError",
    "ReplayInvarianceMismatch",
    "TrendlineReplayContractError",
    "TrendlineReplayError",
    "TrendlineReplayIntegrityError",
    "TrendlineReplayPoint",
    "TrendlineReplayWindow",
    "TrendlineResearchReplaySpec",
    "TrendlineTimeframeReplay",
    "run_causal_replay",
    "validate_replay_point_integrity",
    "validated_replay_points",
    "verify_replay_future_invariance",
]
