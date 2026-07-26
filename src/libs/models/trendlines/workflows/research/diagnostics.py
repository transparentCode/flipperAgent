"""Deterministic, notebook-independent diagnostics for causal replays."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
import json
from typing import Any

import numpy as np
import pandas as pd

from libs.models.trendlines.contracts.identity import canonical_hash
from libs.models.trendlines.pivots.capabilities import TrendlineExecutionMode
from libs.models.trendlines.registry import (
    build_extractor,
    get_registered_extractor_capabilities,
)
from libs.models.trendlines.workflows.research.replay import (
    PreparedTrendlineResearchReplay,
    TrendlineReplayContractError,
    TrendlineReplayPoint,
    validated_replay_points,
)


DIAGNOSTIC_ROW_SEMANTICS_VERSION = "trendlines.research-diagnostics.v2"


class TrendlineDiagnosticError(ValueError):
    """Raised when replay output lacks authoritative diagnostic metadata."""


def _clean(value: Any) -> Any:
    """Convert diagnostic values to deterministic JSON-compatible values."""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _clean(value.item())
    if isinstance(value, np.ndarray):
        return [_clean(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_clean(item) for item in value), key=lambda item: str(item))
    if isinstance(value, float) and not np.isfinite(value):
        return str(value)
    return value


def _point_ids(point: TrendlineReplayPoint) -> dict[str, Any]:
    boundary = point.boundary_identity
    signal = point.signal_identity
    return {
        "replay_point_id": point.replay_point_id,
        "content_id": point.content_id,
        "source_id": point.prefix_source_ref.source_id,
        "checkpoint_id": boundary.checkpoint.checkpoint_id,
        "fit_snapshot_id": point.fit_snapshot_id,
        "fit_revision_id": point.fit_revision_id,
        "boundary_snapshot_id": boundary.snapshot_id,
        "boundary_revision_id": boundary.revision_id,
        "signal_snapshot_id": signal.snapshot_id if signal else None,
        "signal_revision_id": signal.revision_id if signal else None,
    }


def _build_row_evidence_id(
    row_type: str,
    row: Mapping[str, Any],
) -> str:
    payload = {
        "row_type": row_type,
        **{
            key: value
            for key, value in row.items()
            if key != "evidence_id"
        },
        "semantics_version": DIAGNOSTIC_ROW_SEMANTICS_VERSION,
    }
    canonical_payload = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return canonical_hash(
        canonical_payload,
        semantics_version=DIAGNOSTIC_ROW_SEMANTICS_VERSION,
    )


def build_pivot_count_evidence_id(row: Mapping[str, Any]) -> str:
    return _build_row_evidence_id("pivot_count", row)


def build_line_evidence_id(row: Mapping[str, Any]) -> str:
    return _build_row_evidence_id("line", row)


def build_ray_evidence_id(row: Mapping[str, Any]) -> str:
    return _build_row_evidence_id("ray", row)


def build_signal_evidence_id(row: Mapping[str, Any]) -> str:
    return _build_row_evidence_id("signal", row)


@dataclass(frozen=True)
class SnapshotSummaryRow:
    timeframe: str
    position: int
    replay_point_id: str
    content_id: str
    event_at: str
    available_at: str
    source_id: str
    checkpoint_id: str
    fit_snapshot_id: str | None
    fit_revision_id: str | None
    boundary_snapshot_id: str
    boundary_revision_id: str
    signal_snapshot_id: str | None
    signal_revision_id: str | None
    finality: str
    fit_valid: bool
    support_line_count: int
    resistance_line_count: int
    support_ray_count: int
    resistance_ray_count: int
    structure_state: str
    interaction: str
    market_position_state: str
    hull_width_atr: float
    mean_quality: float
    signal_count: int
    composite_direction: float
    composite_confidence: float

    def to_dict(self) -> dict[str, Any]:
        return _clean(self.__dict__)


@dataclass(frozen=True)
class PivotCountRow:
    evidence_id: str
    timeframe: str
    position: int
    event_at: str
    available_at: str
    n_high_pivots: int
    n_low_pivots: int
    extractor: str
    extractor_finality: str
    replay_point_id: str
    content_id: str
    source_id: str
    checkpoint_id: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self.__dict__)


@dataclass(frozen=True)
class LineEvidenceRow:
    evidence_id: str
    timeframe: str
    position: int
    role: str
    ordinal: int
    method: str
    start_position: int
    end_position: int
    start_value: float
    end_value: float
    slope: float
    intercept: float
    touch_count: int
    score: float
    replay_point_id: str
    content_id: str
    source_id: str
    checkpoint_id: str
    boundary_snapshot_id: str
    boundary_revision_id: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self.__dict__)


@dataclass(frozen=True)
class RayEvidenceRow:
    evidence_id: str
    timeframe: str
    position: int
    role: str
    ordinal: int
    start_time: str
    end_time: str
    start_price: float
    end_price: float
    slope: float
    intercept: float
    quality: float
    touch_count: int
    r_squared: float
    replay_point_id: str
    content_id: str
    source_id: str
    checkpoint_id: str
    boundary_snapshot_id: str
    boundary_revision_id: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self.__dict__)


@dataclass(frozen=True)
class SignalEvidenceRow:
    evidence_id: str
    timeframe: str
    position: int
    ordinal: int
    source: str
    name: str
    direction: float
    confidence: float
    metadata: dict[str, Any]
    replay_point_id: str
    content_id: str
    source_id: str
    checkpoint_id: str
    signal_snapshot_id: str | None
    signal_revision_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return _clean(self.__dict__)


@dataclass(frozen=True)
class ReplayPivotRow:
    timeframe: str
    position: int
    pivot_role: str
    bar_position: int
    event_at: str
    price: float
    extractor: str
    extractor_finality: str
    source_id: str
    checkpoint_id: str
    boundary_snapshot_id: str
    boundary_revision_id: str
    replay_point_id: str
    content_id: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self.__dict__)


@dataclass(frozen=True)
class TrendlineReplaySummary:
    timeframe_count: int
    executed_point_count: int
    recorded_snapshot_count: int
    unique_recorded_position_count: int
    valid_point_count: int
    invalid_point_count: int
    support_line_total: int
    resistance_line_total: int
    support_ray_total: int
    resistance_ray_total: int
    signal_total: int
    finality_distribution: dict[str, int]
    structure_state_distribution: dict[str, int]
    interaction_distribution: dict[str, int]
    first_event_at: str | None
    last_event_at: str | None
    first_available_at: str | None
    last_available_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return _clean(self.__dict__)


def _snapshot_rows_from_points(
    replay: PreparedTrendlineResearchReplay,
    points: tuple[TrendlineReplayPoint, ...],
) -> tuple[SnapshotSummaryRow, ...]:
    rows: list[SnapshotSummaryRow] = []
    for point in points:
        timeframe = point.timeframe
        boundary = point.boundary_snapshot.boundary
        fit = point.output.fit_result
        quality = boundary.quality_metrics
        signal = point.output.signal_output or {}
        ids = _point_ids(point)
        rows.append(
            SnapshotSummaryRow(
                timeframe=timeframe,
                position=point.position,
                replay_point_id=ids["replay_point_id"],
                content_id=ids["content_id"],
                event_at=point.event_at.isoformat(),
                available_at=point.available_at.isoformat(),
                source_id=ids["source_id"],
                checkpoint_id=ids["checkpoint_id"],
                fit_snapshot_id=ids["fit_snapshot_id"],
                fit_revision_id=ids["fit_revision_id"],
                boundary_snapshot_id=ids["boundary_snapshot_id"],
                boundary_revision_id=ids["boundary_revision_id"],
                signal_snapshot_id=ids["signal_snapshot_id"],
                signal_revision_id=ids["signal_revision_id"],
                finality=point.boundary_identity.finality.value,
                fit_valid=bool(fit.is_valid),
                support_line_count=len(fit.support_lines),
                resistance_line_count=len(fit.resistance_lines),
                support_ray_count=len(boundary.active_support_rays),
                resistance_ray_count=len(boundary.active_resistance_rays),
                structure_state=boundary.structure_state,
                interaction=boundary.interaction,
                market_position_state=boundary.market_position_state,
                hull_width_atr=float(quality.hull_width_atr) if quality else 0.0,
                mean_quality=float(boundary.mean_normalized_quality),
                signal_count=int(signal.get("signal_count", 0)),
                composite_direction=float(signal.get("composite_direction", 0.0)),
                composite_confidence=float(signal.get("composite_confidence", 0.0)),
            )
        )
    return tuple(rows)


def replay_snapshot_rows(
    replay: PreparedTrendlineResearchReplay,
) -> tuple[SnapshotSummaryRow, ...]:
    return _snapshot_rows_from_points(replay, validated_replay_points(replay))


def _pivot_count_rows_from_points(
    replay: PreparedTrendlineResearchReplay,
    points: tuple[TrendlineReplayPoint, ...],
) -> tuple[PivotCountRow, ...]:
    rows: list[PivotCountRow] = []
    for point in points:
        timeframe = point.timeframe
        metadata = point.output.fit_result.metadata.get("pipeline", {})
        if not isinstance(metadata, dict):
            raise TrendlineDiagnosticError(
                "fit result lacks authoritative pipeline pivot metadata"
            )
        finality = point.boundary_identity.finality.value
        row_payload = {
            "timeframe": timeframe,
            "position": point.position,
            "event_at": point.event_at.isoformat(),
            "available_at": point.available_at.isoformat(),
            "n_high_pivots": int(metadata["n_high_pivots"]),
            "n_low_pivots": int(metadata["n_low_pivots"]),
            "extractor": str(metadata["extractor"]),
            "extractor_finality": finality,
            "replay_point_id": point.replay_point_id,
            "content_id": point.content_id,
            "source_id": point.prefix_source_ref.source_id,
            "checkpoint_id": point.boundary_identity.checkpoint.checkpoint_id,
        }
        rows.append(
            PivotCountRow(
                evidence_id=build_pivot_count_evidence_id(row_payload),
                **row_payload,
            )
        )
    return tuple(rows)


def replay_pivot_count_rows(
    replay: PreparedTrendlineResearchReplay,
) -> tuple[PivotCountRow, ...]:
    return _pivot_count_rows_from_points(replay, validated_replay_points(replay))


def _line_rows_from_points(
    replay: PreparedTrendlineResearchReplay,
    points: tuple[TrendlineReplayPoint, ...],
) -> tuple[LineEvidenceRow, ...]:
    rows: list[LineEvidenceRow] = []
    for point in points:
        timeframe = point.timeframe
        fit = point.output.fit_result
        ids = _point_ids(point)
        for role, lines in (
            ("support", fit.support_lines),
            ("resistance", fit.resistance_lines),
        ):
            for ordinal, line in enumerate(lines):
                row_payload = {
                    "timeframe": timeframe,
                    "position": point.position,
                    "role": role,
                    "ordinal": ordinal,
                    "method": line.method,
                    "start_position": int(line.start_index),
                    "end_position": int(line.end_index),
                    "start_value": float(line.start_value),
                    "end_value": float(line.end_value),
                    "slope": float(line.slope),
                    "intercept": float(line.intercept),
                    "touch_count": int(line.touch_count),
                    "score": float(line.score),
                    "replay_point_id": point.replay_point_id,
                    "content_id": ids["content_id"],
                    "source_id": ids["source_id"],
                    "checkpoint_id": ids["checkpoint_id"],
                    "boundary_snapshot_id": ids["boundary_snapshot_id"],
                    "boundary_revision_id": ids["boundary_revision_id"],
                }
                rows.append(
                    LineEvidenceRow(
                        evidence_id=build_line_evidence_id(row_payload),
                        **row_payload,
                    )
                )
    return tuple(rows)


def replay_line_rows(
    replay: PreparedTrendlineResearchReplay,
) -> tuple[LineEvidenceRow, ...]:
    return _line_rows_from_points(replay, validated_replay_points(replay))


def _ray_rows_from_points(
    replay: PreparedTrendlineResearchReplay,
    points: tuple[TrendlineReplayPoint, ...],
) -> tuple[RayEvidenceRow, ...]:
    rows: list[RayEvidenceRow] = []
    for point in points:
        timeframe = point.timeframe
        boundary = point.boundary_snapshot.boundary
        ids = _point_ids(point)
        for role, rays in (
            ("support", boundary.active_support_rays),
            ("resistance", boundary.active_resistance_rays),
        ):
            for ordinal, ray in enumerate(rays):
                row_payload = {
                    "timeframe": timeframe,
                    "position": point.position,
                    "role": role,
                    "ordinal": ordinal,
                    "start_time": str(ray.start_time),
                    "end_time": str(ray.end_time),
                    "start_price": float(ray.start_price),
                    "end_price": float(ray.end_price),
                    "slope": float(ray.slope),
                    "intercept": float(ray.intercept),
                    "quality": float(ray.normalized_quality_score),
                    "touch_count": int(ray.touch_count),
                    "r_squared": float(ray.r_squared),
                    "replay_point_id": point.replay_point_id,
                    "content_id": ids["content_id"],
                    "source_id": ids["source_id"],
                    "checkpoint_id": ids["checkpoint_id"],
                    "boundary_snapshot_id": ids["boundary_snapshot_id"],
                    "boundary_revision_id": ids["boundary_revision_id"],
                }
                rows.append(
                    RayEvidenceRow(
                        evidence_id=build_ray_evidence_id(row_payload),
                        **row_payload,
                    )
                )
    return tuple(rows)


def replay_ray_rows(
    replay: PreparedTrendlineResearchReplay,
) -> tuple[RayEvidenceRow, ...]:
    return _ray_rows_from_points(replay, validated_replay_points(replay))


def _signal_rows_from_points(
    replay: PreparedTrendlineResearchReplay,
    points: tuple[TrendlineReplayPoint, ...],
) -> tuple[SignalEvidenceRow, ...]:
    rows: list[SignalEvidenceRow] = []
    for point in points:
        timeframe = point.timeframe
        signal_identity = point.signal_identity
        if point.output.signal_output is None:
            continue
        ids = _point_ids(point)
        for ordinal, signal in enumerate(point.output.signal_output.get("signals", [])):
            row_payload = {
                "timeframe": timeframe,
                "position": point.position,
                "ordinal": ordinal,
                "source": str(signal.source),
                "name": str(signal.name),
                "direction": float(signal.direction),
                "confidence": float(signal.confidence),
                "metadata": _clean(dict(signal.metadata)),
                "replay_point_id": point.replay_point_id,
                "content_id": ids["content_id"],
                "source_id": ids["source_id"],
                "checkpoint_id": ids["checkpoint_id"],
                "signal_snapshot_id": (
                    signal_identity.snapshot_id if signal_identity else None
                ),
                "signal_revision_id": (
                    signal_identity.revision_id if signal_identity else None
                ),
            }
            rows.append(
                SignalEvidenceRow(
                    evidence_id=build_signal_evidence_id(row_payload),
                    **row_payload,
                )
            )
    return tuple(rows)


def replay_signal_rows(
    replay: PreparedTrendlineResearchReplay,
) -> tuple[SignalEvidenceRow, ...]:
    return _signal_rows_from_points(replay, validated_replay_points(replay))


def _inspect_replay_pivots_from_point(
    prepared: Any,
    replay: PreparedTrendlineResearchReplay,
    point: TrendlineReplayPoint,
    *,
    timeframe: str,
    position: int,
) -> tuple[ReplayPivotRow, ...]:
    """Re-extract pivots for one recorded point as a diagnostic only."""

    frame = prepared.dataset.frames[timeframe].iloc[: position + 1].copy()
    frame.attrs = dict(prepared.dataset.frames[timeframe].attrs)
    config = prepared.configuration.pipeline_configs[timeframe]
    extractor = build_extractor(
        config.extractor,
        execution_mode=TrendlineExecutionMode.RESEARCH,
        **config.extractor_params,
    )
    pivots = extractor.extract(frame)
    metadata = point.output.fit_result.metadata.get("pipeline", {})
    if int(metadata.get("n_high_pivots", -1)) != pivots.n_highs:
        raise TrendlineDiagnosticError("high pivot count disagrees with pipeline metadata")
    if int(metadata.get("n_low_pivots", -1)) != pivots.n_lows:
        raise TrendlineDiagnosticError("low pivot count disagrees with pipeline metadata")
    capabilities = get_registered_extractor_capabilities(config.extractor)
    identity = point.boundary_identity
    rows: list[ReplayPivotRow] = []
    for role, indices, values in (
        ("high", pivots.high_indices, pivots.high_values),
        ("low", pivots.low_indices, pivots.low_values),
    ):
        for index, value in zip(indices.tolist(), values.tolist()):
            index = int(index)
            rows.append(
                ReplayPivotRow(
                    timeframe=timeframe,
                    position=position,
                    pivot_role=role,
                    bar_position=index,
                    event_at=pd.Timestamp(frame.index[index]).isoformat(),
                    price=float(value),
                    extractor=config.extractor,
                    extractor_finality=capabilities.finality.value,
                    source_id=point.prefix_source_ref.source_id,
                    checkpoint_id=identity.checkpoint.checkpoint_id,
                    boundary_snapshot_id=identity.snapshot_id,
                    boundary_revision_id=identity.revision_id,
                    replay_point_id=point.replay_point_id,
                    content_id=point.content_id,
                )
            )
    return tuple(sorted(rows, key=lambda row: (row.bar_position, row.pivot_role)))


def inspect_replay_pivots(
    prepared: Any,
    replay: PreparedTrendlineResearchReplay,
    *,
    timeframe: str,
    position: int,
) -> tuple[ReplayPivotRow, ...]:
    """Re-extract pivots for one recorded point as a diagnostic only."""

    if replay.prepared is not prepared:
        raise TrendlineReplayContractError("prepared run does not belong to replay")
    point = replay.output_at(timeframe, position)
    return _inspect_replay_pivots_from_point(
        prepared,
        replay,
        point,
        timeframe=timeframe,
        position=position,
    )


def _summary_from_rows(
    replay: PreparedTrendlineResearchReplay,
    rows: tuple[SnapshotSummaryRow, ...],
) -> TrendlineReplaySummary:
    finality = Counter(row.finality for row in rows)
    structure = Counter(row.structure_state for row in rows)
    interaction = Counter(row.interaction for row in rows)
    first_event = min(rows, key=lambda row: pd.Timestamp(row.event_at)) if rows else None
    last_event = max(rows, key=lambda row: pd.Timestamp(row.event_at)) if rows else None
    first_available = (
        min(rows, key=lambda row: pd.Timestamp(row.available_at)) if rows else None
    )
    last_available = (
        max(rows, key=lambda row: pd.Timestamp(row.available_at)) if rows else None
    )
    return TrendlineReplaySummary(
        timeframe_count=len(replay.prepared.spec.timeframes),
        executed_point_count=sum(
            replay.timeframes[timeframe].executed_position_count
            for timeframe in replay.prepared.spec.timeframes
        ),
        recorded_snapshot_count=len(rows),
        unique_recorded_position_count=len(
            {(row.timeframe, row.position) for row in rows}
        ),
        valid_point_count=sum(row.fit_valid for row in rows),
        invalid_point_count=sum(not row.fit_valid for row in rows),
        support_line_total=sum(row.support_line_count for row in rows),
        resistance_line_total=sum(row.resistance_line_count for row in rows),
        support_ray_total=sum(row.support_ray_count for row in rows),
        resistance_ray_total=sum(row.resistance_ray_count for row in rows),
        signal_total=sum(row.signal_count for row in rows),
        finality_distribution=dict(sorted(finality.items())),
        structure_state_distribution=dict(sorted(structure.items())),
        interaction_distribution=dict(sorted(interaction.items())),
        first_event_at=first_event.event_at if first_event else None,
        last_event_at=last_event.event_at if last_event else None,
        first_available_at=first_available.available_at if first_available else None,
        last_available_at=last_available.available_at if last_available else None,
    )


def replay_summary(
    replay: PreparedTrendlineResearchReplay,
) -> TrendlineReplaySummary:
    points = validated_replay_points(replay)
    return _summary_from_rows(replay, _snapshot_rows_from_points(replay, points))


__all__ = [
    "DIAGNOSTIC_ROW_SEMANTICS_VERSION",
    "LineEvidenceRow",
    "PivotCountRow",
    "RayEvidenceRow",
    "ReplayPivotRow",
    "SignalEvidenceRow",
    "SnapshotSummaryRow",
    "TrendlineDiagnosticError",
    "TrendlineReplaySummary",
    "build_line_evidence_id",
    "build_pivot_count_evidence_id",
    "build_ray_evidence_id",
    "build_signal_evidence_id",
    "inspect_replay_pivots",
    "replay_line_rows",
    "replay_pivot_count_rows",
    "replay_ray_rows",
    "replay_signal_rows",
    "replay_snapshot_rows",
    "replay_summary",
]
